"""The 24-hour deletion job. SPEC.md §7.2.

    "Uploaded documents and their derived rows are deleted 24 hours after upload by a scheduled job.
     This is stated on the upload dropzone, because a person about to hand a contract to a
     stranger's website wants to read exactly that sentence."

This is the code that makes that sentence true. Until it existed, the UI promised deletion and
nothing deleted — which is worse than not promising, because a person acted on it.

WHAT GETS DELETED. Everything derived from the upload: the PDF in object storage, the document row,
and by cascade its pages, chunks, analyses, findings, absences, key_terms, and agent_events. The
findings and the trace carry *quoted text from the contract*, so deleting the PDF alone would not be
deletion — it would be theatre.

WHAT SURVIVES, AND WHY. Two things, both deliberately:

  * `users.uploads_used` — the grant counter. It is a fact about what someone consumed, not content
    from their contract, and it must outlive the deletion or the cap refunds itself every night
    (migration 005).
  * `usage_ledger` — a per-month cost total against a hashed key. No contract content, and the
    monthly ceiling depends on it.

Demo documents are never touched: they have `expires_at IS NULL` because they belong to nobody and
are meant to be permanent (migration 001).
"""

from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import asyncpg

from clause.config import settings
from clause.db import pool
from clause.ingest.storage import Storage, get_storage

log = logging.getLogger(__name__)


async def delete_expired(conn: asyncpg.Connection, storage: Storage) -> int:
    """Delete every upload past its expiry. Returns how many went. Safe to run at any time.

    Order matters: the storage object goes FIRST, then the row. If we deleted the row first and the
    object delete then failed, we would have lost the only pointer to that file and it would sit in
    the bucket forever with nothing to find it by. Doing it this way, a failed object delete just
    leaves the row for the next sweep to retry — the file is never orphaned.
    """
    rows = await conn.fetch(
        """
        SELECT id, storage_key FROM documents
        WHERE expires_at IS NOT NULL AND expires_at < now()
        """
    )
    if not rows:
        return 0

    deleted: list[UUID] = []
    for row in rows:
        try:
            # boto3 and file I/O are blocking; a sweep must not stall the event loop the API is
            # serving requests on.
            await asyncio.to_thread(storage.delete, row["storage_key"])
        except Exception:  # noqa: BLE001 — one bad object must not abort the whole sweep
            log.exception(
                "could not delete stored file %s; leaving the row to retry", row["storage_key"]
            )
            continue
        deleted.append(row["id"])

    if deleted:
        # Cascades to pages, chunks, analyses -> findings/absences/key_terms/agent_events.
        await conn.execute("DELETE FROM documents WHERE id = ANY($1::uuid[])", deleted)
        log.info("retention: deleted %d expired document(s)", len(deleted))

    return len(deleted)


async def sweep() -> int:
    """One sweep, against the shared pool. This is what the loop and the CLI both call."""
    p = await pool.pool()
    async with p.acquire() as conn:
        return await delete_expired(conn, get_storage())


async def run_forever() -> None:
    """The scheduler: sweep at boot, then on an interval, until cancelled.

    WHY AN INTERVAL AND NOT A TIGHT POLL. Neon's free tier meters compute-hours and suspends the
    database when idle, so anything that touches Postgres on a timer keeps it awake and burns the
    allowance (ROADMAP.md §5.1). A 5-second poll would cost 720 compute-hours a month doing nothing.
    Hourly costs a couple of hours a day and deletes a file within an hour of its deadline, which
    honours a 24-hour promise without lying about the precision.

    The boot sweep matters more than it looks: a free container sleeps, and while it sleeps nothing
    expires anything. Sweeping the moment it wakes stops a nap turning into a retention hole.
    """
    interval = settings().retention_sweep_minutes * 60
    while True:
        try:
            await sweep()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a scheduler that dies on one bad night is not a scheduler
            log.exception("retention sweep failed; will retry next interval")
        await asyncio.sleep(interval)


def _main() -> None:
    """Run one sweep and exit — for a cron, a scheduled job, or a human.

        cd api && uv run python -m clause.retention

    The in-process loop above covers the container host we run today. This exists so the promise
    does not depend on that choice: any host with a scheduler can call this instead.
    """
    import sys

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    async def once() -> int:
        n = await sweep()
        await pool.close()
        return n

    count = asyncio.run(once())
    print(f"Deleted {count} expired document(s).")


if __name__ == "__main__":
    _main()
