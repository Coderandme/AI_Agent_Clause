"""Parser tests.

The page-offset invariant is the one thing here that MUST NOT break. Everything downstream —
quote verification's page number, the highlight overlay's rectangles — trusts it, and when it
breaks it does so silently: findings simply get attributed to the wrong page. SPEC.md §9.3 is
explicit that "a highlight on the wrong page" is the unacceptable failure.
"""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from clause import text
from clause.config import REPO_ROOT
from clause.ingest import parse

MSA = REPO_ROOT / "demo" / "contracts" / "saas_msa.pdf"


@pytest.fixture(scope="module")
def msa_bytes() -> bytes:
    if not MSA.exists():
        pytest.skip("run `python demo/build_pdfs.py` first")
    return MSA.read_bytes()


def test_parses_the_msa(msa_bytes: bytes) -> None:
    doc = parse.parse(msa_bytes)
    assert doc.page_count == 5
    assert doc.char_count > 5_000
    assert not doc.is_scanned


def test_page_offsets_slice_back_to_the_page(msa_bytes: bytes) -> None:
    """full_text[char_start:char_end] is exactly that page's text, for every page."""
    doc = parse.parse(msa_bytes)
    src = pymupdf.open(stream=msa_bytes, filetype="pdf")

    with src:
        assert len(doc.pages) == src.page_count
        for page in doc.pages:
            sliced = doc.full_text[page.char_start : page.char_end]
            assert sliced == src[page.page_number - 1].get_text("text")


def test_pages_are_contiguous_and_ordered(msa_bytes: bytes) -> None:
    doc = parse.parse(msa_bytes)
    for i, page in enumerate(doc.pages):
        assert page.page_number == i + 1
        assert page.char_start < page.char_end
        if i:
            # Exactly one separator character between one page's end and the next page's start.
            assert page.char_start == doc.pages[i - 1].char_end + len(parse.PAGE_SEPARATOR)


def test_offset_lookup_finds_the_right_page(msa_bytes: bytes) -> None:
    """The lookup quote verification depends on: a character offset -> a page number.

    The clause chosen is the cross-clause trap: §14.2 lifts the indemnity out of the §9 liability
    cap, which is exactly the kind of interaction between distant clauses that SPEC.md §4.1 says
    retrieval would lose and whole-document reading catches.

    Note the quote is matched against NORMALISED text and the offset mapped back through
    `normalized_offsets`. A raw `str.find` fails here, and that failure is not a bug — the PDF
    hard-wraps the clause across lines while the agent will quote it as continuous prose. This is
    exactly the gap SPEC.md §4.5 opens with, and getting it wrong would make every finding
    unverifiable.
    """
    doc = parse.parse(msa_bytes)
    quote = "are not subject to the limitations of liability set out in Section 9"

    flat = text.normalize(doc.full_text)
    offsets = text.normalized_offsets(doc.full_text)

    at = flat.find(text.normalize(quote))
    assert at != -1, "the planted clause is missing from the extracted text"

    offset = offsets[at]  # back into the ORIGINAL text, which `pages` is indexed against
    page_number = doc.page_for_offset(offset)
    assert page_number is not None

    src = pymupdf.open(stream=msa_bytes, filetype="pdf")
    with src:
        page_text = text.normalize(src[page_number - 1].get_text("text"))
        assert text.normalize(quote) in page_text


def test_normalized_offsets_map_back_to_the_original_text(msa_bytes: bytes) -> None:
    """The map must be exact, or a verified quote highlights the wrong span."""
    doc = parse.parse(msa_bytes)
    flat = text.normalize(doc.full_text)
    offsets = text.normalized_offsets(doc.full_text)

    assert len(offsets) == len(flat)

    quote = "renew automatically for successive periods of twenty-four (24) months"
    at = flat.find(text.normalize(quote))
    assert at != -1

    start = offsets[at]
    end = offsets[at + len(text.normalize(quote)) - 1] + 1

    # The span pulled from the ORIGINAL text, re-normalised, is the quote we searched for.
    assert text.normalize(doc.full_text[start:end]) == text.normalize(quote)


def test_offset_past_the_end_has_no_page(msa_bytes: bytes) -> None:
    doc = parse.parse(msa_bytes)
    assert doc.page_for_offset(doc.char_count + 1) is None


def test_rejects_bytes_that_are_not_a_pdf() -> None:
    with pytest.raises(parse.UnparseablePDF):
        parse.parse(b"this is not a pdf, it is a sentence about one")


def test_a_pdf_with_no_extractable_text_is_flagged_as_scanned(tmp_path: Path) -> None:
    """The scanned-PDF guard. We pass extracted text, not page images (SPEC.md §3.2), so a scan
    gives the agent nothing to read — and we reject it at upload rather than return an empty
    analysis. Simulated here with blank pages, which extract to nothing just as a scan does."""
    blank = pymupdf.open()
    for _ in range(3):
        blank.new_page()
    path = tmp_path / "scan.pdf"
    blank.save(path)
    blank.close()

    doc = parse.parse(path.read_bytes())
    assert doc.is_scanned
