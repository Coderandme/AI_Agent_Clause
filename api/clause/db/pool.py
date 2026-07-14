"""Postgres connection pool, and the migration runner.

Deliberately thin. There is no ORM here: the interesting queries in this project — hybrid retrieval
(SPEC.md §3.4) and the FOR UPDATE SKIP LOCKED job claim (§3.5) — are SQL that an ORM would only get
in the way of, and the rest is CRUD.
"""

from __future__ import annotations

from pathlib import Path

import asyncpg

from clause.config import settings

_pool: asyncpg.Pool | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


async def pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            settings().database_url,
            min_size=1,
            # Small on purpose. Neon's free tier meters compute and caps connections, and this
            # process is one container serving a low-traffic portfolio site (ROADMAP.md §5.1).
            max_size=8,
            command_timeout=30,
        )
    return _pool


async def close() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def migrate() -> list[str]:
    """Apply any migration not yet recorded in schema_migrations. Returns the ones applied.

    Each migration runs inside a transaction with its bookkeeping row, so a failure half way through
    leaves the database on the previous version rather than in an undefined one.
    """
    p = await pool()
    async with p.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              name       text PRIMARY KEY,
              applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        done = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}

        applied: list[str] = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            async with conn.transaction():
                await conn.execute(path.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", path.name)
            applied.append(path.name)

        return applied
