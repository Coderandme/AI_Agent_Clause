"""Fetch the eval corpus from SEC EDGAR and render it to PDF.

The eval corpus is REAL contracts, and that is not incidental — it is the whole basis on which the
numbers in SPEC.md §8 mean anything (ROADMAP.md §6).

Grading the agent on the synthetic contracts in demo/ would prove nothing. Those were written to be
caught: every one of the 15 rules fires, the clauses are planted in plain sight, and the first real
run scored 15 findings out of 15 rules with zero absences. That tells us nothing about precision,
because a scan that flags everything is right about everything on a document where everything is
wrong.

Real filed contracts are different. Most rules genuinely do NOT fire. The clauses that do fire are
buried in cross-references, defined terms, and schedules. That is where recall and precision start
to mean something.

SEC EDGAR publishes thousands of commercial agreements as exhibits to public filings. They are free,
public, and exactly as unpleasant to read as real contracts are, which is the property we want.

    python evals/build_corpus.py
"""

from __future__ import annotations

import html
import re
import time
import urllib.request
from pathlib import Path

import pymupdf

CORPUS = Path(__file__).parent / "corpus"

# SEC requires a User-Agent identifying the requester. This is their rule, not a workaround.
UA = {"User-Agent": "Clause portfolio project bijeeta1@gmail.com"}

# Chosen for size and for being genuine arms-length commercial agreements where the FILER is the
# customer — the same position as our reader (SPEC.md §2.1).
DOCUMENTS = [
    (
        "salesforce_msa",
        "https://www.sec.gov/Archives/edgar/data/1428669/000119312508062588/dex1028.htm",
        "salesforce.com Master Subscription Agreement — filed by SolarWinds as EX-10.28. "
        "SolarWinds is the CUSTOMER here, which is our reader's position exactly.",
    ),
    (
        "wejo_msa",
        "https://www.sec.gov/Archives/edgar/data/1864448/000110465921093068/tm2121431d2_ex10-8.htm",
        "Wejo Master Subscription Agreement — EX-10.8.",
    ),
    (
        "tearlab_agreement",
        "https://www.sec.gov/Archives/edgar/data/1299139/000143774914004299/ex10-1.htm",
        "TearLab commercial supply agreement — EX-10.1. A different contract shape from the two "
        "SaaS agreements, so the corpus is not three of the same thing.",
    ),
]

PAGE = pymupdf.paper_rect("letter")
MARGIN = 64
SIZE = 10.0
LEADING = 14.0


def strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</h\d>|</td>", "\n", raw)
    raw = re.sub(r"<[^>]+>", "", raw)
    text = html.unescape(raw)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # EDGAR prepends the exhibit's own filing chrome. Drop everything before the contract title so
    # the agent is not analysing a filename and a page count.
    lines = text.split("\n")
    for i, line in enumerate(lines[:12]):
        if re.match(r"^\s*(MASTER|SOFTWARE|SERVICES?|SUBSCRIPTION)\b", line.strip(), re.I):
            lines = lines[i:]
            break
    return "\n".join(lines).strip()


def render(text: str, dest: Path) -> int:
    doc = pymupdf.open()
    font = pymupdf.Font("times-roman")
    page = doc.new_page(width=PAGE.width, height=PAGE.height)
    writer = pymupdf.TextWriter(page.rect)
    y = MARGIN
    width = PAGE.width - 2 * MARGIN

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            y += LEADING * 0.5
            continue

        for chunk in _wrap(line, width, font):
            if y + LEADING > PAGE.height - MARGIN:
                writer.write_text(page)
                page = doc.new_page(width=PAGE.width, height=PAGE.height)
                writer = pymupdf.TextWriter(page.rect)
                y = MARGIN
            writer.append((MARGIN, y), chunk, fontsize=SIZE, font=font)
            y += LEADING

    writer.write_text(page)
    doc.save(dest)
    n = doc.page_count
    doc.close()
    return n


def _wrap(line: str, width: float, font: pymupdf.Font) -> list[str]:
    out: list[str] = []
    current = ""
    for word in line.split():
        candidate = f"{current} {word}".strip()
        if font.text_length(candidate, fontsize=SIZE) <= width:
            current = candidate
        else:
            if current:
                out.append(current)
            current = word
    if current:
        out.append(current)
    return out or [""]


def main() -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)

    for slug, url, label in DOCUMENTS:
        pdf = CORPUS / f"{slug}.pdf"
        try:
            raw = urllib.request.urlopen(
                urllib.request.Request(url, headers=UA)
            ).read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"  {slug:<20} FAILED: {exc}")
            continue

        text = strip_html(raw)
        pages = render(text, pdf)
        print(f"  {slug:<20} {pages:>2} pages  {label}")

        # Provenance, so the README can say exactly where each document came from. An eval corpus
        # whose origin is unclear is an eval corpus nobody can check.
        (CORPUS / f"{slug}.source.txt").write_text(f"{label}\n{url}\n", encoding="utf-8")
        time.sleep(0.2)  # be polite to EDGAR


if __name__ == "__main__":
    main()
