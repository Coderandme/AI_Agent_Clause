"""Run the agent on an uploaded document and persist the result. SPEC.md §4, §6.3.

This is the bridge the CLI (clause/analyse.py) and the demo pre-baker (clause/demo.py) always had
but the web path did not: upload → run the four rule-family passes → write findings, absences, key
terms, and the trace to Postgres → record what it cost. It is the same agent and the same quote
verification; only the destination changes (a database row instead of a terminal).

HOW IT RUNS, AND WHY NOT INSIDE THE REQUEST. An analysis takes 40-70 seconds (SPEC.md §1.2), far too
long to hold an HTTP request open across a free-tier proxy. So the upload route creates a `queued`
analysis row, returns its id immediately, and schedules `run_and_store` as a background task; the
SPA polls GET /api/analyses/{id} until it flips to `complete` or `failed`.

This is the simple in-process version of SPEC.md §3.5's job queue. The durable Postgres queue with
crash-recovery is deferred (ROADMAP.md V1) — if the container restarts mid-analysis the row is left
`running` and the user re-uploads. At invite-only volume that is an acceptable trade; the schema
(`jobs`, `agent_events`) is already in place for the durable version when it is worth building.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from openai import AsyncOpenAI

from clause import guard, models, rules
from clause.agent import loop
from clause.agent.execute import AnalysisState, ToolExecutor
from clause.agent.verify import DocumentIndex
from clause.config import settings
from clause.db import pool
from clause.retrieval.search import index_document

log = logging.getLogger(__name__)


@dataclass(slots=True)
class ScanOutput:
    state: AnalysisState
    usage: loop.Usage
    summary: str | None
    trace: list[dict[str, Any]]
    turns: int
    seconds: float


async def create_analysis(conn: Any, document_id: UUID, *, spec: models.ModelSpec) -> UUID:
    """Insert the `queued` row and return its id, so the route can hand it back before work starts.

    scan_model and extract_model are both the scan model on purpose: in V1 the key terms are
    recorded by the agent DURING the scan (the record_key_terms tool), not by a separate cheaper
    call — so it is the model that produced them. A separate mini extraction pass comes later.
    """
    analysis_id = uuid4()
    await conn.execute(
        """
        INSERT INTO analyses
          (id, document_id, status, scan_model, extract_model, rule_library_version)
        VALUES ($1, $2, 'queued', $3, $4, $5)
        """,
        analysis_id,
        document_id,
        spec.id,
        spec.id,
        rules.library_version(),
    )
    return analysis_id


async def run_and_store(analysis_id: UUID, document_id: UUID, spend_key: str) -> None:
    """The background job: run the scan and write the result. Never raises — a failure is recorded
    on the analysis row and surfaced to the user honestly, not swallowed into a spinner forever.

    `spend_key` is what the usage ledger hashes to attribute the cost. We pass the user's id rather
    than an IP: at invite-only volume the ledger exists only to feed the monthly ceiling's SUM, and
    attributing spend to the account that caused it is more useful than to a proxy address.
    """
    spec = models.for_task(models.Task.RISK_SCAN)
    p = await pool.pool()

    # Load the document text and page map. Done in a short-lived connection: the 60-second scan must
    # NOT hold a Neon connection open (ROADMAP.md §5.1), so we read, release, scan, then reacquire.
    async with p.acquire() as conn:
        await conn.execute(
            "UPDATE analyses SET status = 'running', started_at = now() WHERE id = $1", analysis_id
        )
        full_text = await conn.fetchval(
            "SELECT full_text FROM documents WHERE id = $1", document_id
        )
        page_rows = await conn.fetch(
            """
            SELECT page_number, char_start, char_end FROM pages
            WHERE document_id = $1 ORDER BY page_number
            """,
            document_id,
        )

    if not full_text:
        await _fail(analysis_id, "The document has no extractable text to analyse.")
        return

    # Index for Q&A (V2): chunk + embed into `chunks`. ~1-2s and ~$0.0006 next to a 60-80s scan.
    # Non-fatal on purpose — the risk scan is the marquee; if indexing fails, Q&A degrades to
    # "not indexed" and the scan proceeds untouched.
    try:
        async with p.acquire() as conn:
            await index_document(
                conn, AsyncOpenAI(api_key=settings().openai_api_key), document_id, full_text
            )
    except Exception:  # noqa: BLE001 — Q&A is optional; the scan is not
        log.exception("indexing %s for Q&A failed; continuing with the scan", document_id)

    pages = [(r["page_number"], r["char_start"], r["char_end"]) for r in page_rows]

    try:
        out = await _run_scan(full_text, pages, spec)
    except loop.AgentRefused as exc:
        await _fail(analysis_id, f"The model declined to analyse this document. ({exc})")
        return
    except loop.AgentTurnLimitExceeded as exc:
        await _fail(analysis_id, f"The analysis did not converge and was stopped. ({exc})")
        return
    except Exception as exc:  # noqa: BLE001 — a background job must record its failure, not vanish
        log.exception("analysis %s crashed", analysis_id)
        await _fail(analysis_id, f"The analysis failed: {type(exc).__name__}.")
        return

    await _store_success(analysis_id, spec, out, spend_key)


async def _run_scan(
    full_text: str, pages: list[tuple[int, int, int]], spec: models.ModelSpec
) -> ScanOutput:
    """Four rule-family passes, warm-then-fan-out — the same orchestration as clause/analyse.py and
    clause/demo.py, here for a real (non-eval) run that persists its result."""
    index = DocumentIndex(full_text, pages)
    state = AnalysisState()
    execute = ToolExecutor(index, state)
    client = AsyncOpenAI(api_key=settings().openai_api_key)

    trace: list[dict[str, Any]] = []
    started = time.monotonic()

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        trace.append({"at": round(time.monotonic() - started, 2), "kind": kind, **payload})

    async def run(family: rules.Family) -> loop.PassResult:
        return await loop.run_pass(
            client,
            family=family,
            document_text=full_text,
            execute_tool=execute,
            emit=emit,
            model=spec,
        )

    # Warm the cached prefix on one pass, then fan the other three out against it (SPEC.md §4.2).
    families = list(rules.Family)
    first = await run(families[0])
    rest = await asyncio.gather(*(run(f) for f in families[1:]))
    results = [first, *rest]

    usage = loop.Usage()
    for r in results:
        usage.input_tokens += r.usage.input_tokens
        usage.cached_input_tokens += r.usage.cached_input_tokens
        usage.output_tokens += r.usage.output_tokens

    return ScanOutput(
        state=state,
        usage=usage,
        summary=first.summary,
        trace=trace,
        turns=sum(r.turns for r in results),
        seconds=round(time.monotonic() - started, 1),
    )


async def _store_success(
    analysis_id: UUID, spec: models.ModelSpec, out: ScanOutput, spend_key: str
) -> None:
    cost = out.usage.cost_microdollars(spec)
    token_usage = {
        "input_tokens": out.usage.input_tokens,
        "cached_input_tokens": out.usage.cached_input_tokens,
        "output_tokens": out.usage.output_tokens,
    }
    findings = out.state.verified_findings

    p = await pool.pool()
    async with p.acquire() as conn, conn.transaction():
        await conn.execute(
            """
            UPDATE analyses SET
              status = 'complete', summary = $2, turns_used = $3, unverified_count = $4,
              token_usage = $5::jsonb, cost_microdollars = $6, completed_at = now()
            WHERE id = $1
            """,
            analysis_id,
            out.summary,
            out.turns,
            out.state.unverified_count,
            json.dumps(token_usage),
            cost,
        )

        if findings:
            await conn.executemany(
                """
                INSERT INTO findings (
                  id, analysis_id, rule_id, severity, title, exposure, recommendation,
                  quoted_text, matched_text, char_start, char_end, page_number, verified, confidence
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,true,$13)
                """,
                [
                    (
                        uuid4(),
                        analysis_id,
                        f.rule_id,
                        f.severity,
                        f.title,
                        f.exposure,
                        f.recommendation,
                        f.quoted_text,
                        f.matched_text,
                        f.char_start,
                        f.char_end,
                        f.page_number,
                        f.confidence,
                    )
                    for f in findings
                ],
            )

        if out.state.absences:
            await conn.executemany(
                "INSERT INTO absences (analysis_id, rule_id, rationale) VALUES ($1, $2, $3)",
                [(analysis_id, a.rule_id, a.rationale) for a in out.state.absences],
            )

        if out.state.key_terms is not None:
            await conn.execute(
                "INSERT INTO key_terms (analysis_id, payload) VALUES ($1, $2::jsonb)",
                analysis_id,
                json.dumps(out.state.key_terms),
            )

        if out.trace:
            await conn.executemany(
                """
                INSERT INTO agent_events (analysis_id, seq, kind, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                """,
                [
                    (analysis_id, seq, event["kind"], json.dumps(event))
                    for seq, event in enumerate(out.trace)
                ],
            )

        # Record the cost LAST, inside the same transaction, so the ledger and the analysis row can
        # never disagree. This is what finally arms the monthly ceiling (guard.py).
        await guard.record_spend(conn, ip=spend_key, cost_microdollars=cost)


async def _fail(analysis_id: UUID, message: str) -> None:
    p = await pool.pool()
    async with p.acquire() as conn:
        await conn.execute(
            "UPDATE analyses SET status = 'failed', error = $2, completed_at = now() WHERE id = $1",
            analysis_id,
            message,
        )
