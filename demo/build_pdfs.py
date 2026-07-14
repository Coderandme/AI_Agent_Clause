"""Render the synthetic demo contracts from .txt to .pdf.

The demo corpus is SYNTHETIC and must be documented as such in the README (SPEC.md §13.4) — a demo
that implies real contracts were scraped is a credibility hole, not a shortcut.

Keeping the source as plain text and rendering to PDF here means the planted clauses stay reviewable
and diffable in git, which a binary PDF would not be.

Note this is the DEMO corpus, not the EVAL corpus. The two exist for opposite reasons (ROADMAP.md
§6): these are written to produce dramatic findings for a visitor; the eval corpus is real contracts
from SEC EDGAR, because an agent graded on contracts written to be catchable proves nothing.

    python demo/build_pdfs.py
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

CONTRACTS_DIR = Path(__file__).parent / "contracts"

PAGE = pymupdf.paper_rect("letter")
MARGIN = 64
FONT = "times-roman"
BOLD = "times-bold"
SIZE = 10.5
LEADING = 15.0


def render(source: Path, dest: Path) -> int:
    doc = pymupdf.open()
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    y = MARGIN
    bottom = PAGE.height - MARGIN

    for raw in source.read_text(encoding="utf-8").split("\n"):
        line = raw.strip()

        if not line:
            y += LEADING * 0.5
            continue

        # A heading is a numbered section head or the title: short, and mostly capitals.
        is_heading = line.isupper() or (
            line[0].isdigit() and "." in line[:4] and line[:40].isupper()
        )
        font = BOLD if is_heading else FONT
        if is_heading:
            y += LEADING * 0.4

        writer = pymupdf.TextWriter(page.rect)
        wrapped = _wrap(line, PAGE.width - 2 * MARGIN, font)

        for chunk in wrapped:
            if y + LEADING > bottom:
                writer.write_text(page)
                page = doc.new_page(width=PAGE.width, height=PAGE.height)
                writer = pymupdf.TextWriter(page.rect)
                y = MARGIN
            writer.append((MARGIN, y), chunk, fontsize=SIZE, font=pymupdf.Font(font))
            y += LEADING

        writer.write_text(page)

    doc.save(dest)
    n = doc.page_count
    doc.close()
    return n


def _wrap(line: str, width: float, fontname: str) -> list[str]:
    font = pymupdf.Font(fontname)
    words = line.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.text_length(candidate, fontsize=SIZE) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


if __name__ == "__main__":
    for src in sorted(CONTRACTS_DIR.glob("*.txt")):
        out = src.with_suffix(".pdf")
        pages = render(src, out)
        print(f"{src.name} -> {out.name}  ({pages} pages)")
