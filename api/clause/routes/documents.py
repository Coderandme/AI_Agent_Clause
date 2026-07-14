"""Document routes. SPEC.md §6.1.

The upload is a multipart POST straight from the browser to this service, not proxied through the
Next.js frontend (ROADMAP.md §2.1).

Note what is NOT here yet: rate limiting and the spend ceiling. Those are M7, and they gate this
endpoint. Until they land, the upload path is open — which is fine locally and would not be fine on
a public URL. Do not deploy this route without them.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile

from clause.db import pool
from clause.ingest.service import UploadRejected, ingest
from clause.ingest.storage import get_storage

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("", status_code=202)
async def upload(file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008 — FastAPI idiom
    data = await file.read()

    p = await pool.pool()
    async with p.acquire() as conn:
        try:
            result = await ingest(
                conn,
                get_storage(),
                data=data,
                filename=file.filename or "contract.pdf",
            )
        except UploadRejected as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc

    # 202, not 200: the document exists, the analysis does not yet. Enqueuing the `analyse` job and
    # returning an analysis_id lands in M3 with the job queue.
    return {
        "document_id": str(result.document_id),
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
