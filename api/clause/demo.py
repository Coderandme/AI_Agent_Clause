"""Pre-compute the demo analyses. SPEC.md §7.1.

    python -m clause.demo

Runs the agent once against each sample contract and freezes the entire result — findings, key
terms, and the FULL agent trace — into JSON on disk.

This is the single most important cost decision in the project. Demo mode is the DEFAULT path on
the landing page: clicking a sample contract costs ZERO API calls and renders instantly, trace
replay and all. Most visitors never upload anything, and they still see the product work.

The trace is real, not fabricated. It is what the agent actually did, recorded as it did it, and
replayed at a plausible speed. Watching it call get_rule_detail("auto_renewal"), then
record_finding, is what makes it legibly agentic rather than a prompt with a spinner in front of it.

Re-run this whenever the prompt, the rule library, or the scan model changes — otherwise the demo
shows the output of a system that no longer exists.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

from clause import models, rules
from clause.agent import loop, prompts
from clause.agent.execute import AnalysisState, ToolExecutor
from clause.agent.verify import DocumentIndex
from clause.config import REPO_ROOT, settings
from clause.ingest import parse

OUT = REPO_ROOT / "demo" / "precomputed"

SAMPLES: list[tuple[str, Path, str]] = [
    (
        "saas_msa",
        REPO_ROOT / "demo" / "contracts" / "saas_msa.pdf",
        "SaaS Master Services Agreement — synthetic, written for this project and seeded with "
        "realistic adverse clauses. Note the liability cap in §9 that §14.2 quietly lifts the "
        "indemnity out of, five pages later.",
    ),
    (
        "salesforce_msa",
        REPO_ROOT / "evals" / "corpus" / "salesforce_msa.pdf",
        "salesforce.com Master Subscription Agreement — a REAL contract, filed with the SEC by "
        "SolarWinds (EX-10.28), who were the customer. This is the one the eval harness grades "
        "against a hand-written answer key.",
    ),
]


async def precompute(slug: str, pdf: Path, blurb: str, spec: models.ModelSpec) -> dict[str, Any]:
    doc = parse.parse(pdf.read_bytes())
    index = DocumentIndex(
        doc.full_text, [(p.page_number, p.char_start, p.char_end) for p in doc.pages]
    )
    state = AnalysisState()
    execute = ToolExecutor(index, state)
    client = AsyncOpenAI(api_key=settings().openai_api_key)

    # The trace, captured exactly as it happens. Replayed later at a plausible speed.
    trace: list[dict[str, Any]] = []
    started = time.monotonic()

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        trace.append({"at": round(time.monotonic() - started, 2), "kind": kind, **payload})

    async def run(family: rules.Family) -> loop.PassResult:
        return await loop.run_pass(
            client,
            family=family,
            document_text=doc.full_text,
            execute_tool=execute,
            emit=emit,
            model=spec,
        )

    families = list(rules.Family)
    first = await run(families[0])
    rest = await asyncio.gather(*(run(f) for f in families[1:]))

    usage = loop.Usage()
    for r in [first, *rest]:
        usage.input_tokens += r.usage.input_tokens
        usage.cached_input_tokens += r.usage.cached_input_tokens
        usage.output_tokens += r.usage.output_tokens

    elapsed = time.monotonic() - started

    return {
        "slug": slug,
        "filename": pdf.name,
        "blurb": blurb,
        "page_count": doc.page_count,
        "char_count": doc.char_count,
        "scan_model": spec.id,
        "rule_library_version": rules.library_version(),
        "prompt_version": prompts.prompt_version(),
        "summary": first.summary,
        "findings": [asdict(f) for f in state.verified_findings],
        "unverified_count": state.unverified_count,
        "absences": [asdict(a) for a in state.absences],
        "key_terms": state.key_terms,
        "trace": trace,
        "usage": {
            "input_tokens": usage.input_tokens,
            "cached_input_tokens": usage.cached_input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_microdollars": usage.cost_microdollars(spec),
        },
        "seconds": round(elapsed, 1),
    }


async def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    OUT.mkdir(parents=True, exist_ok=True)
    spec = models.for_task(models.Task.RISK_SCAN)

    for slug, pdf, blurb in SAMPLES:
        if not pdf.exists():
            print(f"  {slug}: no such file {pdf}")
            continue
        print(f"  {slug}: analysing on {spec.id}…")
        result = await precompute(slug, pdf, blurb, spec)
        (OUT / f"{slug}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")

        # The PDF travels with the precomputed result so the demo is self-contained.
        (OUT / f"{slug}.pdf").write_bytes(pdf.read_bytes())

        print(
            f"    {len(result['findings'])} findings · {len(result['absences'])} absences · "
            f"{len(result['trace'])} trace events · "
            f"${result['usage']['cost_microdollars'] / 1e6:.3f} · {result['seconds']}s"
        )

    print(f"\nWritten to {OUT}. Demo mode now costs $0.00 per view.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
