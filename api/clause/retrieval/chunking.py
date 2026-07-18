"""Split a contract into retrievable chunks. SPEC.md §6.x (ingest): "split on numbered-section
regex, then pack to ~800 tokens with 100-token overlap; carry section_label forward."

THE ONE INVARIANT THAT MATTERS: every chunk's text is a VERBATIM SLICE of the document —
`chunk.text == full_text[chunk.char_start:chunk.char_end]`, always. The offsets are what turn a
retrieved chunk back into a page number (via the `pages` table) and a highlight, exactly the way a
verified finding's quote does. A chunker that normalises, trims, or rewrites text as it goes breaks
that chain silently, so this one never edits — it only slices. The test suite pins the invariant.

WHY SECTIONS AND NOT FIXED WINDOWS. Contracts are already divided by their authors into numbered
clauses, and a clause is the natural unit of meaning — "9.2 Limitation of Liability" wants to be
retrieved whole, with its label attached so an answer can say *where* it came from. Fixed windows
would routinely cut a cap off from its carve-out. So: find the section boundaries, keep sections
whole where possible, pack small neighbours together to amortise per-chunk overhead, and only split
a section when it alone exceeds the budget.

TOKENS ARE APPROXIMATED as chars/4. The budget exists to keep chunks comfortably inside embedding
and context limits, not to hit 800.0 exactly — a tokenizer dependency for a soft target is weight
without value. English legal prose runs ~4 chars/token, so 800 tokens ≈ 3200 chars.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

CHARS_PER_TOKEN = 4
TARGET_TOKENS = 800
OVERLAP_TOKENS = 100

MAX_CHARS = TARGET_TOKENS * CHARS_PER_TOKEN  # 3200
OVERLAP_CHARS = OVERLAP_TOKENS * CHARS_PER_TOKEN  # 400

# A section heading at the start of a line. Three families, matching how real contracts are headed:
#   "9." / "9.2" / "14.2.1 Indemnification"      — bare numbered clauses
#   "Section 9" / "ARTICLE IV"                    — worded headings
#   "SCHEDULE A" / "Exhibit B" / "Appendix 1"     — attachments
# False positives (a numbered list inside a clause) cost an extra boundary, which is harmless;
# false negatives cost a merged section, also harmless. This is a packing heuristic, not a parser.
_HEADING = re.compile(
    r"""^[ \t]*(?:
        (?P<num>\d{1,2}(?:\.\d{1,2}){0,3})[.)]?[ \t]+(?=\S)
      | (?:Section|SECTION|Article|ARTICLE)[ \t]+(?P<word>[0-9IVXLC]+[A-Za-z0-9.]*)
      | (?P<attach>(?:SCHEDULE|Schedule|EXHIBIT|Exhibit|APPENDIX|Appendix)[ \t]+[A-Z0-9]{1,4})\b
    )""",
    re.MULTILINE | re.VERBOSE,
)


@dataclass(slots=True)
class Chunk:
    ordinal: int
    section_label: str | None
    char_start: int
    char_end: int
    text: str  # always full_text[char_start:char_end] — see the module docstring


def _label(m: re.Match[str]) -> str:
    if m.group("num"):
        return m.group("num")
    if m.group("word"):
        return f"Section {m.group('word')}"
    return " ".join((m.group("attach") or "").split())


def _sections(full_text: str) -> list[tuple[str | None, int, int]]:
    """(label, start, end) covering the whole document, in order, no gaps."""
    matches = list(_HEADING.finditer(full_text))
    if not matches:
        return [(None, 0, len(full_text))]

    sections: list[tuple[str | None, int, int]] = []
    if matches[0].start() > 0:
        sections.append((None, 0, matches[0].start()))  # preamble before the first heading
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)
        sections.append((_label(m), m.start(), end))
    return sections


def _split_point(full_text: str, hard_end: int, window_start: int) -> int:
    """Cut at whitespace near the budget boundary rather than mid-word, when one is close by."""
    ws = full_text.rfind(" ", max(window_start + 1, hard_end - 200), hard_end)
    return ws + 1 if ws != -1 else hard_end


def chunk_text(full_text: str) -> list[Chunk]:
    """The whole document → ordered chunks. Total coverage: every character lands in ≥1 chunk."""
    if not full_text.strip():
        return []

    # Pass 1: pack whole sections greedily; split any section that alone busts the budget.
    # Each entry is (label, start, end) of a would-be chunk, offsets into full_text.
    spans: list[tuple[str | None, int, int]] = []
    open_label: str | None = None
    open_start = -1  # -1: no pack currently open

    def close() -> None:
        nonlocal open_start
        if open_start >= 0:
            spans.append((open_label, open_start, close_at))
        open_start = -1

    close_at = 0
    for label, start, end in _sections(full_text):
        if open_start >= 0 and (end - open_start) <= MAX_CHARS:
            close_at = end  # section fits into the open pack — extend it
            continue
        close()
        if (end - start) <= MAX_CHARS:
            open_label, open_start, close_at = label, start, end  # starts a fresh pack
            continue
        # A single section bigger than the budget: window it, keeping its label on every piece.
        pos = start
        while pos < end:
            hard_end = min(pos + MAX_CHARS, end)
            cut = hard_end if hard_end == end else _split_point(full_text, hard_end, pos)
            spans.append((label, pos, cut))
            if cut >= end:
                break
            pos = max(cut - OVERLAP_CHARS, pos + 1)  # step back for overlap; always advance
    close()

    # Pass 2: inter-pack overlap. Each chunk after the first starts OVERLAP_CHARS before the
    # previous chunk's end (unless it already overlaps, i.e. came from a windowed section), so a
    # sentence straddling a boundary is whole in at least one chunk.
    chunks: list[Chunk] = []
    prev_end = 0
    for i, (label, start, end) in enumerate(spans):
        if i > 0 and start >= prev_end:
            start = max(prev_end - OVERLAP_CHARS, 0)
        chunks.append(
            Chunk(
                ordinal=i,
                section_label=label,
                char_start=start,
                char_end=end,
                text=full_text[start:end],
            )
        )
        prev_end = end
    return chunks
