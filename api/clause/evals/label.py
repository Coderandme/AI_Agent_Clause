"""Labelling tools — for the human writing the answer key.

    python -m clause.evals.label new   evals/corpus/salesforce_msa.pdf   # make a worksheet
    python -m clause.evals.label check evals/labels/salesforce_msa.yaml  # check your work

WHAT LABELLING IS, AND WHAT IT IS NOT
─────────────────────────────────────
It is NOT training. Nothing here trains, fine-tunes, or teaches the model anything. The model
arrives from OpenAI already trained and stays frozen, and it never sees these labels. If it could,
the measurement would be worthless — a student who has seen the exam paper.

It is an ANSWER KEY. You read the contract, work through the 15 rules, and record which ones should
fire and which clause is the evidence. `make eval` then runs the agent and compares its output to
what you wrote. Every number in SPEC.md §8 falls out of that comparison:

    recall     — of the rules you said should fire, how many did the agent catch?
    precision  — of the rules it fired, how many were real?
    anchor     — did the span it quoted overlap the clause you pointed at?

Without the key, none of those questions have answers, and "is it any good?" gets answered with an
adjective instead of a number.

WHY `check` EXISTS
──────────────────
Because the answer key can be wrong, and a wrong key is worse than no key — it silently mismarks
the agent forever. So `check` runs every clause you quote through the SAME verification the agent's
quotes go through (agent/verify.py). If a clause you pasted is not actually in the document
verbatim — a typo, a dropped word, a paste from the wrong page — you find out in seconds instead of
never.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from clause import rules
from clause.agent.verify import DocumentIndex, verify
from clause.ingest import parse

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"

LABELS_DIR = Path(__file__).resolve().parents[3] / "evals" / "labels"
CORPUS_DIR = Path(__file__).resolve().parents[3] / "evals" / "corpus"


HEADER = """\
# ANSWER KEY — {slug}
#
# Source: {source}
#
# You are writing the exam paper's answer key. For each of the 15 rules below, decide whether the
# contract contains that problem, and record the evidence.
#
# For each rule, set:
#
#   fires:  true   the contract HAS this problem
#           false  it does not  (this is a TRUE NEGATIVE and it is just as valuable —
#                  it is how we measure whether the agent invents findings)
#
#   When fires: true, you must also give:
#     severity:  critical | high | medium | low   (how much it exposes the CUSTOMER)
#     clause:    the sentence(s) from the contract that prove it, copied EXACTLY.
#                Run `check` afterwards and it will tell you if the copy is wrong.
#
#   When fires: false, delete the severity and clause lines. Optionally add a note.
#
# Take your time on the ones you are unsure about, and mark them `unsure: true` rather than
# guessing. A key with three honest "unsure" flags is worth more than one with fifteen confident
# guesses, because we can exclude them from the metric and say so.
#
# When you are done:
#     python -m clause.evals.label check evals/labels/{slug}.yaml

document: {slug}
labelled_by: bijeeta
rules:
"""

STUB = """
  # {title}
  # {exposure}
  - rule_id: {rule_id}
    fires: TODO          # true | false
    # severity: {default_severity}
    # clause: |
    #   paste the exact clause here
"""


def new(pdf: Path) -> int:
    slug = pdf.stem
    doc = parse.parse(pdf.read_bytes())
    lib = rules.load()

    source_file = pdf.with_suffix("").with_suffix(".source.txt")
    source = source_file.read_text(encoding="utf-8").strip() if source_file.exists() else "unknown"

    out = LABELS_DIR / f"{slug}.yaml"
    if out.exists():
        print(f"{out} already exists — not overwriting.")
        return 1

    body = HEADER.format(slug=slug, source=source.replace("\n", " · "))
    for rule in sorted(lib.rules, key=lambda r: (r.family.value, r.id)):
        body += STUB.format(
            rule_id=rule.id,
            title=rule.title,
            exposure=" ".join(rule.exposure.split()),
            default_severity=rule.default_severity,
        )

    LABELS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(body, encoding="utf-8")

    # A plain-text copy with page markers, so clauses can be found and copied without fighting a
    # PDF viewer's text selection.
    reading = LABELS_DIR / f"{slug}.reading.txt"
    chunks = []
    for page in doc.pages:
        chunks.append(f"\n{'=' * 90}\nPAGE {page.page_number}\n{'=' * 90}\n")
        chunks.append(doc.full_text[page.char_start : page.char_end])
    reading.write_text("".join(chunks), encoding="utf-8")

    print(f"{BOLD}{slug}{OFF}  {doc.page_count} pages")
    print(f"  worksheet   {out}")
    print(f"  read this   {reading}   {DIM}(page-marked, copy clauses from here){OFF}")
    print(f"\nWhen done:  python -m clause.evals.label check evals/labels/{slug}.yaml")
    return 0


def check(label_file: Path) -> int:
    """Verify the answer key against the document it describes.

    Every clause is run through the same guard the agent's quotes are run through. A label whose
    clause is not in the document verbatim would silently mismark the agent forever.
    """
    data = yaml.safe_load(label_file.read_text(encoding="utf-8"))
    slug = data["document"]

    pdf = CORPUS_DIR / f"{slug}.pdf"
    if not pdf.exists():
        print(f"No such document: {pdf}", file=sys.stderr)
        return 2

    doc = parse.parse(pdf.read_bytes())
    index = DocumentIndex(
        doc.full_text, [(p.page_number, p.char_start, p.char_end) for p in doc.pages]
    )
    lib = rules.load()

    known = {r.id for r in lib.rules}
    seen: set[str] = set()
    problems = 0
    fires = 0
    negatives = 0
    todo = 0

    print(f"{BOLD}{slug}{OFF}  {doc.page_count} pages\n")

    for entry in data.get("rules") or []:
        rule_id = entry.get("rule_id")
        seen.add(rule_id)

        if rule_id not in known:
            print(f"{RED}✗{OFF} {rule_id}: not a rule in rules/v1.yaml")
            problems += 1
            continue

        state = entry.get("fires")
        if state not in (True, False):
            print(f"{DIM}○{OFF} {rule_id:<30} {DIM}not yet decided{OFF}")
            todo += 1
            problems += 1
            continue

        if state is False:
            print(f"{DIM}·{OFF} {rule_id:<30} does not fire  {DIM}(true negative){OFF}")
            negatives += 1
            continue

        fires += 1
        clause = (entry.get("clause") or "").strip()
        if not clause:
            print(f"{RED}✗{OFF} {rule_id}: fires, but no clause given — what is the evidence?")
            problems += 1
            continue

        result = verify(clause, index)
        if result.verified:
            sev = entry.get("severity", "?")
            unsure = f"  {DIM}[unsure]{OFF}" if entry.get("unsure") else ""
            print(f"{GREEN}✓{OFF} {rule_id:<30} {sev:<9} page {result.page_number}{unsure}")
        else:
            print(f"{RED}✗{OFF} {rule_id:<30} CLAUSE NOT FOUND IN THE DOCUMENT")
            print(f"    {DIM}{result.reason}{OFF}")
            print(f"    {DIM}you wrote: {' '.join(clause.split())[:70]}…{OFF}")
            problems += 1

    missing = known - seen
    for rule_id in sorted(missing):
        print(f"{RED}✗{OFF} {rule_id}: missing from the answer key — every rule needs a verdict")
        problems += 1

    broken = problems - todo

    print()
    print("─" * 70)
    print(
        f"{BOLD}{fires}{OFF} fire · {BOLD}{negatives}{OFF} true negatives · "
        f"{BOLD}{todo}{OFF} still to decide · {BOLD}{broken}{OFF} broken"
    )

    if todo:
        print(f"{DIM}{len(known) - todo}/{len(known)} rules decided.{OFF}")
    if broken:
        print(f"\n{RED}Fix the broken labels above, then run check again.{OFF}")
    if problems:
        return 1

    print(f"\n{GREEN}Answer key is valid.{OFF} Every clause you quoted exists in the document.")
    print(f"{DIM}{fires} findings the agent must catch, {negatives} it must not invent.{OFF}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="clause.evals.label")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_new = sub.add_parser("new", help="create a blank answer key for a contract")
    p_new.add_argument("pdf", type=Path)

    p_check = sub.add_parser("check", help="verify an answer key against its contract")
    p_check.add_argument("yaml", type=Path)

    args = ap.parse_args()
    if args.cmd == "new":
        return new(args.pdf)
    return check(args.yaml)


if __name__ == "__main__":
    raise SystemExit(main())
