"""Document routes. SPEC.md §6.1.

The upload is a multipart POST straight from the browser to this service, not proxied through the
React SPA (ROADMAP.md §2.1).

Uploading is INVITE-ONLY (SPEC.md §2.5): the route requires a logged-in user, and
`assert_can_upload` enforces their grant and the hard global ceiling before any work is done. A
stranger cannot reach this endpoint at all — there is no anonymous upload path to abuse.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from clause import models
from clause.analysis import service as analysis
from clause.auth.deps import CurrentUser, assert_can_upload
from clause.db import pool
from clause.ingest.service import UploadRejected, ingest
from clause.ingest.storage import get_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", status_code=202)
async def upload(
    user: CurrentUser,
    background: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI idiom
) -> dict[str, Any]:
    data = await file.read()
    spec = models.for_task(models.Task.RISK_SCAN)

    p = await pool.pool()
    async with p.acquire() as conn:
        # Gate first: refuse before spending a byte of work if the user is out of grant or the
        # month's ceiling is reached. Raises 403 / 402 with a message the UI shows verbatim.
        await assert_can_upload(conn, user)
        try:
            result = await ingest(
                conn,
                get_storage(),
                data=data,
                filename=file.filename or "contract.pdf",
                owner_user_id=user.id,
            )
        except UploadRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

        # Don't pay to analyse the same document twice. If this document already has an analysis
        # that hasn't failed (a re-upload of an identical file dedupes to the same document — see
        # ingest/service.py), reuse it rather than spending another ~$0.33 on the same contract.
        existing = await conn.fetchval(
            "SELECT id FROM analyses WHERE document_id = $1 AND status <> 'failed' LIMIT 1",
            result.document_id,
        )
        if existing is not None:
            analysis_id = existing
            schedule = False
        else:
            # Create the analysis row now (status 'queued') so we can hand its id back immediately.
            analysis_id = await analysis.create_analysis(conn, result.document_id, spec=spec)
            schedule = True

    if schedule:
        # The scan takes 40-70s — far too long to hold the request open — so it runs after the
        # response is sent. The SPA polls GET /api/analyses/{id} until it completes.
        background.add_task(analysis.run_and_store, analysis_id, result.document_id, str(user.id))

    # 202 Accepted: the document exists and the analysis is under way (or done, on a re-upload).
    return {
        "document_id": str(result.document_id),
        "analysis_id": str(analysis_id),
        "page_count": result.page_count,
        "char_count": result.char_count,
        "deduplicated": result.deduplicated,
    }


@router.get("/{document_id}")
async def get_document(document_id: UUID) -> dict[str, Any]:
    p = await pool.pool()
    async with p.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, filename, source, page_count, char_count, created_at, expires_at
            FROM documents WHERE id = $1
            """,
            document_id,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="No such document.")

    return {
        "id": str(row["id"]),
        "filename": row["filename"],
        "source": row["source"],
        "page_count": row["page_count"],
        "char_count": row["char_count"],
        "created_at": row["created_at"].isoformat(),
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
    }


@router.get("/{document_id}/file")
async def get_file_url(document_id: UUID) -> dict[str, str]:
    """A signed URL the browser fetches the PDF from directly — see ingest/storage.py."""
    p = await pool.pool()
    async with p.acquire() as conn:
        key = await conn.fetchval("SELECT storage_key FROM documents WHERE id = $1", document_id)

    if key is None:
        raise HTTPException(status_code=404, detail="No such document.")

    return {"url": get_storage().signed_url(key)}
