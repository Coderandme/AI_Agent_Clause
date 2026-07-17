"""Ingest: validate -> hash -> store -> parse -> persist.

SPEC.md §6.3. V1 stops after `pages`. Chunking and embedding join this pipeline in V2, when the Ask
tab needs retrieval — the risk scan does not (SPEC.md §4.1), so building them now would be building
something the marquee feature never calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import asyncpg

from clause.config import settings
from clause.ingest import parse as parser
from clause.ingest.storage import Storage, storage_key


class UploadRejected(Exception):
    """Rejected at the door. The message is shown to the user, so it must be honest and specific —
    "invalid file" tells a person nothing they can act on."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class IngestedDocument:
    document_id: UUID
    page_count: int
    char_count: int
    deduplicated: bool


async def ingest(
    conn: asyncpg.Connection,
    storage: Storage,
    *,
    data: bytes,
    filename: str,
    source: str = "upload",
    owner_session: str | None = None,
    owner_user_id: UUID | None = None,
) -> IngestedDocument:
    s = settings()

    # ── validate ─────────────────────────────────────────────────────────────────────────────────
    if not data:
        raise UploadRejected("The file is empty.")

    if len(data) > s.max_upload_bytes:
        mb = s.max_upload_bytes / 1_048_576
        raise UploadRejected(
            f"That file is {len(data) / 1_048_576:.1f} MB. The limit is {mb:.0f} MB."
        )

    try:
        parsed = parser.parse(data)
    except parser.UnparseablePDF as exc:
        raise UploadRejected(f"That file could not be read as a PDF: {exc}") from exc

    if parsed.page_count > s.max_pages:
        raise UploadRejected(
            f"That document is {parsed.page_count} pages. The limit is {s.max_pages}."
        )

    # SPEC.md §6.3. We pass extracted text, not page images, so a scanned document gives the agent
    # nothing to work with. Reject it honestly rather than returning a confidently empty analysis.
    if parsed.is_scanned:
        raise UploadRejected(
            "That PDF appears to be a scan — it contains images of text rather than text itself, "
            "so there is nothing for us to read. Clause cannot analyse scanned documents yet."
        )

    # ── dedupe ───────────────────────────────────────────────────────────────────────────────────
    # Per owner for uploads (migration 004): the same user re-uploading the same file collapses onto
    # their existing row and is not charged twice, but two different accounts get their own rows so
    # one account never sees another's document and every account's grant is counted honestly.
    digest = sha256(data).hexdigest()
    if source == "upload" and owner_user_id is not None:
        existing = await conn.fetchrow(
            """
            SELECT id, page_count, char_count FROM documents
            WHERE sha256 = $1 AND source = $2 AND owner_user_id = $3
            """,
            digest,
            source,
            owner_user_id,
        )
    else:
        existing = await conn.fetchrow(
            "SELECT id, page_count, char_count FROM documents WHERE sha256 = $1 AND source = $2",
            digest,
            source,
        )
    if existing is not None:
        return IngestedDocument(
            document_id=existing["id"],
            page_count=existing["page_count"],
            char_count=existing["char_count"],
            deduplicated=True,
        )

    # ── store + persist ──────────────────────────────────────────────────────────────────────────
    document_id = uuid4()
    key = storage_key(document_id)  # generated, never the user's filename (SPEC.md §7.4)
    storage.put(key, data)

    # Uploads evaporate after 24h, and the dropzone says so. Demo documents are permanent.
    expires_at = (
        datetime.now(UTC) + timedelta(hours=s.upload_ttl_hours) if source == "upload" else None
    )

    async with conn.transaction():
        await conn.execute(
            """
            INSERT INTO documents (
              id, sha256, filename, source, page_count, char_count,
              is_scanned, storage_key, full_text, owner_session, owner_user_id, expires_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
            """,
            document_id,
            digest,
            filename,
            source,
            parsed.page_count,
            parsed.char_count,
            parsed.is_scanned,
            key,
            parsed.full_text,
            owner_session,
            owner_user_id,
            expires_at,
        )
        await conn.executemany(
            """
            INSERT INTO pages (document_id, page_number, char_start, char_end)
            VALUES ($1,$2,$3,$4)
            """,
            [(document_id, p.page_number, p.char_start, p.char_end) for p in parsed.pages],
        )

        # Charge the grant, in the same transaction that creates the document. A counter rather than
        # a count of rows, because the 24h deletion job (retention.py) removes those rows — and
        # counting them would hand the grant back every night (migration 005). Only a NEW document
        # charges: a deduplicated re-upload returns above and never reaches here.
        if owner_user_id is not None:
            await conn.execute(
                "UPDATE users SET uploads_used = uploads_used + 1 WHERE id = $1", owner_user_id
            )

    return IngestedDocument(
        document_id=document_id,
        page_count=parsed.page_count,
        char_count=parsed.char_count,
        deduplicated=False,
    )
