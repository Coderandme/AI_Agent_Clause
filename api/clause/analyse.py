"""The M2 deliverable, verbatim from SPEC.md §10:

    `python -m clause.analyse sample.pdf` prints verified findings with page numbers to the
    terminal. Quote verification rejects a deliberately corrupted quote.

No database, no queue, no web server. Just: a PDF goes in, and a verified risk review comes out.

    python -m clause.analyse ../demo/contracts/saas_msa.pdf
    python -m clause.analyse ../demo/contracts/saas_msa.pdf --model gpt-5.4-mini
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from clause import models, rules
from clause.agent import loop
from clause.agent.execute import AnalysisState, ToolExecutor
from clause.agent.verify import DocumentIndex
from clause.config import settings
from clause.ingest import parse

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}

DIM = "\033[2m"
BOLD = "\033[1m"
RED = "\033[31m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
GREEN = "\033[32m"
OFF = "\033[0m"

SEVERITY_COLOUR = {"critical": RED, "high": RED, "medium": YELLOW, "low": BLUE}


async def analyse(path: Path, *, model: models.ModelSpec, quiet: bool) -> int:
    doc = parse.parse(path.read_bytes())
    print(
        f"{BOLD}{path.name}{OFF}  {doc.page_count} pages, {doc.char_count:,} chars"
        f"  {DIM}scan model: {model.id}{OFF}\n"
    )

    if doc.is_scanned:
        print("This looks like a scanned PDF — there is no extractable text to analyse.")
        return 1

    index = DocumentIndex(
        full_text=doc.full_text,
        pages=[(p.page_number, p.char_start, p.char_end) for p in doc.pages],
    )
    state = AnalysisState()
    execute = ToolExecutor(index, state)
    client = AsyncOpenAI(api_key=settings().openai_api_key)

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        """The agent trace. In M3 this writes to `agent_events` and streams over SSE; here it
        prints. It is a feature, not a debug panel — watching the agent call get_rule_detail, then
        record_finding, is what makes it legibly agentic."""
        if quiet:
            return
        if kind == "tool_call":
            name = payload["name"]
            args = payload["input"]
            detail = args.get("rule_id") or ""
            print(f"  {DIM}→ {name}({detail}){OFF}")
        elif kind == "tool_result":
            out = payload["output"]
            if payload["name"] == "record_finding":
                if out.get("verified"):
                    print(f"    {GREEN}✓ verified, page {out['page']}{OFF}")
                else:
                    print(f"    {RED}✗ QUOTE REJECTED — finding discarded{OFF}")
        elif kind == "reasoning":
            text = payload["text"].strip().replace("\n", " ")
            if text:
                print(f"  {DIM}{text[:100]}{OFF}")

    started = time.monotonic()

    async def run(family: rules.Family) -> loop.PassResult:
        return await loop.run_pass(
            client,
            family=family,
            document_text=doc.full_text,
            execute_tool=execute,
            emit=emit,
            model=model,
        )

    # The four rule-family passes are INDEPENDENT — nothing in LIABILITY informs TERMINATION — so
    # running them in sequence is 4x the wall clock for no benefit. Serial, a 5-page contract took
    # 237s against a 90s budget for a 30-page one (SPEC.md §1.2).
    #
    # But they cannot simply all be fired at once, because prompt caching is a PREFIX MATCH against
    # a prefix the API has already SEEN. Launch all four simultaneously and all four MISS the cache,
    # because none has finished writing it yet — trading a 4x speedup for a 4x input bill.
    #
    # So: run the first pass alone to warm the prefix, then fan out the rest against a warm cache.
    # One serial pass, three parallel, and both the latency budget and the caching design hold.
    families = list(rules.Family)

    first = await run(families[0])
    rest = await asyncio.gather(*(run(f) for f in families[1:]))
    results = [first, *rest]

    total = loop.Usage()
    for r in results:
        total.input_tokens += r.usage.input_tokens
        total.cached_input_tokens += r.usage.cached_input_tokens
        total.output_tokens += r.usage.output_tokens
        pct = (
            100 * r.usage.cached_input_tokens / r.usage.input_tokens if r.usage.input_tokens else 0
        )
        print(
            f"{BOLD}{r.family.value:<18}{OFF}{DIM}{r.turns} turns · "
            f"{r.usage.input_tokens:,} in ({pct:.0f}% cached) · {r.usage.output_tokens:,} out{OFF}"
        )
    print()

    elapsed = time.monotonic() - started
    _report(state, total, model, elapsed)
    return 0


def _report(
    state: AnalysisState, usage: loop.Usage, model: models.ModelSpec, elapsed: float
) -> None:
    findings = sorted(
        state.verified_findings, key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.rule_id)
    )

    print("─" * 96)
    print(f"{BOLD}FINDINGS{OFF}  ({len(findings)} verified)\n")

    for f in findings:
        colour = SEVERITY_COLOUR.get(f.severity, "")
        print(f"{colour}{BOLD}[{f.severity.upper()}]{OFF} {BOLD}{f.title}{OFF}")
        print(f"{DIM}{f.rule_id} · page {f.page_number} · confidence {f.confidence}{OFF}")
        print(f"  {f.exposure}")
        print(f'  {DIM}"{_clip(f.matched_text or f.quoted_text)}"{OFF}')
        print(f"  {GREEN}→{OFF} {f.recommendation}\n")

    if state.absences:
        print(f"{BOLD}CHECKED AND NOT FOUND{OFF}  ({len(state.absences)})")
        for a in sorted(state.absences, key=lambda a: a.rule_id):
            print(f"  {DIM}·{OFF} {a.rule_id}: {a.rationale}")
        print()

    if state.key_terms:
        print(f"{BOLD}KEY TERMS{OFF}")
        for key, value in state.key_terms.items():
            shown = value if value else f"{DIM}Not specified{OFF}"
            if isinstance(shown, list):
                shown = ", ".join(shown)
            print(f"  {key:<20} {shown}")
        print()

    print("─" * 96)

    # The hallucination guard, made visible. This is the number that decides whether the product's
    # central claim is true, and the eval gate fails the build above 0.15 (SPEC.md §4.5).
    attempted = len(state.findings)
    rejected = state.unverified_count
    rate = rejected / attempted if attempted else 0.0
    flag = f" {RED}⚠ ABOVE 0.15 GATE{OFF}" if rate > 0.15 else ""
    print(
        f"{BOLD}Quote verification{OFF}  {attempted - rejected}/{attempted} verified · "
        f"{rejected} rejected ({rate:.0%}){flag}"
    )

    cost = usage.cost_microdollars(model)
    cached_pct = 100 * usage.cached_input_tokens / usage.input_tokens if usage.input_tokens else 0
    print(
        f"{BOLD}Cost{OFF}               ${cost / 1e6:.3f}  ·  "
        f"{usage.input_tokens:,} in ({cached_pct:.0f}% cached), {usage.output_tokens:,} out"
    )
    print(f"{BOLD}Wall clock{OFF}         {elapsed:.1f}s")


def _clip(text: str, limit: int = 150) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit] + "…"


def main() -> int:
    # Windows consoles default to cp1252, which cannot encode the trace's arrows and check marks.
    # Without this the analysis runs, spends real money, and then dies on a print statement.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="clause.analyse")
    ap.add_argument("pdf", type=Path)
    ap.add_argument(
        "--model",
        default=None,
        help="override the scan model, e.g. gpt-5.4-mini. Defaults to the tier in models.py.",
    )
    ap.add_argument("--quiet", action="store_true", help="suppress the agent trace")
    args = ap.parse_args()

    if not args.pdf.exists():
        print(f"No such file: {args.pdf}", file=sys.stderr)
        return 2

    spec = models.for_task(models.Task.RISK_SCAN)
    if args.model:
        match = next((m for m in models.SWEEP_TIERS if m.id == args.model), None)
        if match is None:
            known = ", ".join(m.id for m in models.SWEEP_TIERS)
            print(f"Unknown model {args.model!r}. Known: {known}", file=sys.stderr)
            return 2
        spec = match

    if not settings().openai_api_key:
        print("OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2

    return asyncio.run(analyse(args.pdf, model=spec, quiet=args.quiet))


if __name__ == "__main__":
    raise SystemExit(main())
