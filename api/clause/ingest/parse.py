"""PDF parsing. PyMuPDF -> full text + per-page character offsets.

This file is small and load-bearing out of all proportion to its size. Two things downstream depend
on the offsets it produces being exactly right:

  * Quote verification (SPEC.md §4.5) finds a quote's character span in `full_text` and needs to
    turn that span into a PAGE NUMBER. It does that by looking it up in `pages`.
  * The highlight overlay (SPEC.md §9.3) takes the same span and paints it onto the PDF.

So there is one invariant here, and it is worth stating explicitly because everything rests on it:

    full_text[page.char_start:page.char_end] == that page's text, exactly.

If that ever drifts, findings get attributed to the wrong page — and SPEC.md §9.3 is blunt that a
slightly imprecise highlight is fine but "a highlight on the wrong page is not". `_check_invariant`
asserts it at parse time so it can never drift silently.

We deliberately do NOT send the PDF to OpenAI (SPEC.md §3.2): its file input rasterises every page
into an image and bills you for thirty images you did not need. We extract the text ourselves — and
we need these offsets anyway.
"""

from __future__ import annotations

from dataclasses import dataclass

import pymupdf

from clause.config import settings

# Pages are joined by a form feed. A single character keeps the offset arithmetic trivial, and it
# is one that never appears inside extracted contract text — so a quote can never accidentally
# span the join and match across a page boundary.
PAGE_SEPARATOR = "\f"


@dataclass(frozen=True, slots=True)
class Page:
    page_number: int  # 1-indexed, as the reader sees it
    char_start: int  # inclusive offset into full_text
    char_end: int  # exclusive


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    full_text: str
    pages: list[Page]

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def char_count(self) -> int:
        return len(self.full_text)

    @property
    def is_scanned(self) -> bool:
        """A scanned PDF is images of text, so extraction yields almost nothing.

        Because we pass extracted text rather than page images (SPEC.md §3.2), such a document gives
        the agent nothing to analyse. v1 rejects it at upload with an honest message rather than
        producing a confidently empty analysis (SPEC.md §6.3).
        """
        if not self.pages:
            return True
        return (self.char_count / self.page_count) < settings().min_chars_per_page

    def page_for_offset(self, offset: int) -> int | None:
        """Which page does this character offset fall on? The lookup that turns a verified quote
        into a page number."""
        for page in self.pages:
            if page.char_start <= offset < page.char_end:
                return page.page_number
        return None


class UnparseablePDF(Exception):
    """The bytes are not a PDF we can read. Untrusted input; expected, not exceptional."""


def parse(data: bytes) -> ParsedDocument:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — PyMuPDF raises a wide variety on malformed input
        raise UnparseablePDF(str(exc)) from exc

    with doc:
        if doc.needs_pass:
            raise UnparseablePDF("the PDF is password-protected")

        parts: list[str] = []
        pages: list[Page] = []
        cursor = 0

        for i, page in enumerate(doc):
            # "text" preserves reading order as PyMuPDF sees it. That ordering is the thing most
            # likely to disagree with pdf.js's text layer on multi-column or table-heavy pages,
            # which is the known risk in SPEC.md §9.3 — and why the overlay has a page-level
            # fallback rather than a promise.
            text: str = page.get_text("text")

            pages.append(Page(page_number=i + 1, char_start=cursor, char_end=cursor + len(text)))
            parts.append(text)
            cursor += len(text) + len(PAGE_SEPARATOR)

        full_text = PAGE_SEPARATOR.join(parts)

    parsed = ParsedDocument(full_text=full_text, pages=pages)
    _check_invariant(parsed, parts)
    return parsed


def _check_invariant(parsed: ParsedDocument, parts: list[str]) -> None:
    """full_text[char_start:char_end] must be exactly that page's text.

    Cheap to check, catastrophic to get wrong, and silent when it breaks — so we check it on every
    parse rather than trusting the arithmetic above.
    """
    for page, expected in zip(parsed.pages, parts, strict=True):
        actual = parsed.full_text[page.char_start : page.char_end]
        if actual != expected:
            raise AssertionError(
                f"page offset invariant violated on page {page.page_number}: "
                f"full_text[{page.char_start}:{page.char_end}] does not match the page text"
            )
