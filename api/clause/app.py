"""FastAPI application — the backend JSON API.

The React SPA (web/) is a separate static build and talks to this service over HTTP for everything
dynamic: signup, login, upload. It does NOT talk to it for the demo — the pre-computed demo analyses
are bundled into the SPA itself, so the demo renders with no backend at all and does not wait for
this container to wake from sleep (ROADMAP.md §2.1, §5.2).

Uploads and the eventual SSE trace go straight from the browser to this origin rather than being
proxied, because an SSE connection held open for 40-70 seconds has no business inside a serverless
function's duration ceiling.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from clause import models, retention, rules
from clause.auth import routes as auth_routes
from clause.config import settings
from clause.db import pool
from clause.routes import analyses, documents


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail at boot if the rule library is malformed, rather than at turn nineteen of an analysis.
    rules.load()
    await pool.migrate()

    # The 24-hour deletion job (SPEC.md §7.2). It sweeps at boot and then hourly, which makes
    # the dropzone's "deleted after 24 hours" promise true. Disabled by setting the interval to 0 —
    # for a host where a cron calls `python -m clause.retention` instead.
    sweeper: asyncio.Task[None] | None = None
    if settings().retention_sweep_minutes > 0:
        sweeper = asyncio.create_task(retention.run_forever())

    yield

    if sweeper is not None:
        sweeper.cancel()
        with suppress(asyncio.CancelledError):
            await sweeper
    await pool.close()


app = FastAPI(title="Clause", version="0.1.0", lifespan=lifespan)

# The SPA is served from a different origin (Vite in dev, a static host in production), so the
# browser will not call this API without an explicit CORS allowance. Locked to known origins rather
# than "*" — the API carries the JWT that gates spending, and a wildcard would let any page on the
# internet call it with a victim's token.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://127.0.0.1:5173",
        *settings().cors_extra_origins,  # the deployed SPA's origin, set in .env
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

app.include_router(auth_routes.router)
app.include_router(documents.router)
app.include_router(analyses.router)


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
