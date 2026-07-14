"""FastAPI application.

The browser talks to this service directly for uploads and for the two SSE endpoints, rather than
through the Next.js frontend — SSE connections are held open for 40-70 seconds and there is no
reason to put a serverless function's duration ceiling in the middle of that (ROADMAP.md §2.1).

Reads of finished data go straight from Next.js to Postgres and never reach this process at all,
which is what keeps the demo path working while this container is asleep (ROADMAP.md §5.2).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from clause import models, rules
from clause.db import pool
from clause.routes import documents


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail at boot if the rule library is malformed, rather than at turn nineteen of an analysis.
    rules.load()
    await pool.migrate()
    yield
    await pool.close()


app = FastAPI(title="Clause", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # + the Vercel origin, once it exists
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(documents.router)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """SPEC.md §6.1: db, queue depth, spend headroom.

    Spend headroom lands with the ledger in M7. Queue depth is reported now because a queue that is
    backing up is the first symptom of a wedged worker, and a health check that cannot show it is
    not worth much.
    """
    db_ok = False
    queue_depth: int | None = None

    try:
        p = await pool.pool()
        async with p.acquire() as conn:
            await conn.execute("SELECT 1")
            queue_depth = await conn.fetchval("SELECT count(*) FROM jobs WHERE status = 'queued'")
        db_ok = True
    except Exception:  # noqa: BLE001 — health checks report, they do not raise
        db_ok = False

    lib = rules.load()

    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "queue_depth": queue_depth,
        "rules": {
            "count": len(lib.rules),
            "version": rules.library_version(),
        },
        "models": {
            "risk_scan": models.for_task(models.Task.RISK_SCAN).id,
            "key_terms": models.for_task(models.Task.KEY_TERMS).id,
        },
    }
