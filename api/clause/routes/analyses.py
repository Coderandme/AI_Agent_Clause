"""Read an analysis and its result. SPEC.md §6.1.

The SPA polls GET /api/analyses/{id} after an upload until `status` flips to `complete` or `failed`,
then renders the findings. The response is shaped deliberately like the pre-computed demo files
(demo/precomputed/*.json) so the frontend renders a live analysis with the SAME
components it uses for the demo — one set of finding cards, one trace view, one key-terms table.

Only VERIFIED findings are stored and returned (SPEC.md §4.5): a finding whose quote could not be
located in the document never reaches the user. The count of rejected ones is `unverified_count`.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException

from clause.auth.deps import CurrentUser
from clause.db import pool

router = APIRouter(prefix="/api/analyses", tags=["analyses"])


@router.get("/{analysis_id}")
async def get_analysis(analysis_id: UUID, user: CurrentUser) -> dict[str, Any]:
    p = await pool.pool()
    async with p.acquire() as conn:
        analysis = await conn.fetchrow(
            """
            SELECT a.id, a.document_id, a.status, a.scan_model, a.summary, a.unverified_count,
                   a.cost_microdollars, a.error, a.started_at, a.completed_at,
                   d.owner_user_id, d.filename, d.page_count
            FROM analyses a JOIN documents d ON d.id = a.document_id
            WHERE a.id = $1
            """,
            analysis_id,
        )
        if analysis is None:
            raise HTTPException(status_code=404, detail="No such analysis.")

        # You may only read an analysis of a document you own. Admins may read any — useful for
        # support, and harmless since there is no other tenant's data worth hiding from the author.
        if analysis["owner_user_id"] != user.id and not user.is_admin:
            raise HTTPException(status_code=404, detail="No such analysis.")

        result: dict[str, Any] = {
            "id": str(analysis["id"]),
            "status": analysis["status"],
            "error": analysis["error"],
            "filename": analysis["filename"],
            "page_count": analysis["page_count"],
            "scan_model": analysis["scan_model"],
            "summary": analysis["summary"],
            "unverified_count": analysis["unverified_count"],
            "cost_microdollars": analysis["cost_microdollars"],
            "seconds": _seconds(analysis["started_at"], analysis["completed_at"]),
            "findings": [],
            "absences": [],
            "key_terms": None,
        }

        if analysis["status"] != "complete":
            return result  # nothing to render yet (or it failed — `error` carries why)

        findings = await conn.fetch(
            """
            SELECT rule_id, severity, title, exposure, recommendation, quoted_text, confidence,
                   verified, matched_text, char_start, char_end, page_number
            FROM findings WHERE analysis_id = $1
            ORDER BY CASE severity
              WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, rule_id
            """,
            analysis_id,
        )
        absences = await conn.fetch(
            "SELECT rule_id, rationale FROM absences WHERE analysis_id = $1 ORDER BY rule_id",
            analysis_id,
        )
        key_terms = await conn.fetchval(
            "SELECT payload FROM key_terms WHERE analysis_id = $1", analysis_id
        )

    result["findings"] = [dict(r) for r in findings]
    result["absences"] = [dict(r) for r in absences]
    # payload is jsonb; asyncpg returns it as a JSON string, so parse it back for the client.
    result["key_terms"] = _json_or_none(key_terms)
    return result


def _seconds(started: Any, completed: Any) -> float | None:
    if started is None or completed is None:
        return None
    return round(float((completed - started).total_seconds()), 1)


def _json_or_none(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        import json

        return json.loads(value)
    return value
