"""Spend caps and access control for the public demo. SPEC.md §7.

The application sits on a public URL with anonymous uploads. Strangers will spend the author's API
budget, and a bot that finds the endpoint will spend all of it. This module is what stands between
them and it.

THE TWO-POOL DESIGN, AND WHY A SINGLE GLOBAL CAP IS NOT ENOUGH
──────────────────────────────────────────────────────────────
The obvious design is one global ceiling: when monthly spend hits it, disable uploads and degrade to
demo mode. That protects the wallet — and it breaks at exactly the wrong moment.

Picture it: a bot drains the budget on a Tuesday. On Thursday the author opens their own project in
an interview to show it off, and it says "uploads disabled". The cap protected the money by
sabotaging the only reason the money was being spent.

So the budget is split into two pools:

    ANONYMOUS   small.  drained by whoever shows up.  one upload per session.
    RESERVED    larger. requires an access code.      cannot be touched by strangers.

A bot can empty the anonymous pool. It cannot touch the reserve. The demo still works for anyone the
author has given a code to, on the day it matters.

Demo mode is unaffected by either pool, because it costs nothing at all — it replays a pre-computed
analysis (SPEC.md §7.1). Most visitors never upload anything, and they still see the product work.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from clause.config import settings


@dataclass(frozen=True, slots=True)
class Decision:
    allowed: bool
    reason: str = ""
    # Which pool this analysis would be billed to. Recorded so the ledger can tell them apart.
    pool: str = "anonymous"


def hash_ip(ip: str) -> str:
    """The raw IP is NEVER stored. Only HMAC(ip, secret) — SPEC.md §7.2.

    A person handing their contract to a stranger's website deserves not to have their address in
    that stranger's database.
    """
    return hmac.new(settings().ip_hash_secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[
        :32
    ]


def check_access_code(code: str | None) -> bool:
    """Constant-time comparison. A timing side-channel on a demo access code is not a real threat,
    but writing `==` here would be the kind of thing a reviewer notices."""
    expected = settings().access_code
    if not expected or not code:
        return False
    return hmac.compare_digest(code.strip(), expected)


async def month_spend_microdollars(conn: asyncpg.Connection, pool: str | None = None) -> int:
    """Total spent this calendar month, optionally within one pool."""
    now = datetime.now(UTC)
    query = """
        SELECT COALESCE(SUM(cost_microdollars), 0) FROM usage_ledger
        WHERE day >= date_trunc('month', $1::date)
    """
    args: list[object] = [now.date()]
    if pool is not None:
        query += " AND pool = $2"
        args.append(pool)
    return int(await conn.fetchval(query, *args) or 0)


async def may_analyse(
    conn: asyncpg.Connection, *, ip: str, access_code: str | None, session_uploads: int
) -> Decision:
    """Checked BEFORE the job is enqueued, never after. SPEC.md §7.2.

    Checking afterwards would mean the money is already spent, which is not a cap — it is a
    postmortem.
    """
    s = settings()
    authorised = check_access_code(access_code)
    pool = "reserved" if authorised else "anonymous"

    # ── the hard global ceiling. nothing crosses it, code or no code. ────────────────────────────
    total = await month_spend_microdollars(conn)
    if total >= s.monthly_ceiling_microdollars:
        return Decision(
            allowed=False,
            reason=(
                "This month's analysis budget is spent. The sample contracts below still work — "
                "they are pre-computed and cost nothing to view."
            ),
            pool=pool,
        )

    if authorised:
        return Decision(allowed=True, pool="reserved")

    # ── anonymous visitors ───────────────────────────────────────────────────────────────────────
    anon = await month_spend_microdollars(conn, pool="anonymous")
    if anon >= s.anonymous_ceiling_microdollars:
        return Decision(
            allowed=False,
            reason=(
                "The budget for anonymous uploads is spent for this month. The sample contracts "
                "below are pre-computed and still work. If you have an access code, enter it above."
            ),
        )

    if session_uploads >= s.max_uploads_per_session:
        return Decision(
            allowed=False,
            reason=(
                f"Anonymous visitors get {s.max_uploads_per_session} upload. The sample contracts "
                f"are unlimited — they cost nothing to view."
            ),
        )

    # Per-IP daily cap, on top of the per-session one, because a session is trivially reset by
    # opening a new tab and is therefore not a limit at all.
    today = datetime.now(UTC).date()
    used = await conn.fetchval(
        "SELECT analyses FROM usage_ledger WHERE day = $1 AND ip_hash = $2",
        today,
        hash_ip(ip),
    )
    if (used or 0) >= s.max_analyses_per_ip_per_day:
        return Decision(
            allowed=False,
            reason=(
                f"That's {s.max_analyses_per_ip_per_day} analyses today from this address. "
                f"The sample contracts are unlimited."
            ),
        )

    return Decision(allowed=True, pool="anonymous")


async def record_spend(
    conn: asyncpg.Connection, *, ip: str, pool: str, cost_microdollars: int
) -> None:
    await conn.execute(
        """
        INSERT INTO usage_ledger (day, ip_hash, pool, analyses, cost_microdollars)
        VALUES ($1, $2, $3, 1, $4)
        ON CONFLICT (day, ip_hash, pool) DO UPDATE
          SET analyses          = usage_ledger.analyses + 1,
              cost_microdollars = usage_ledger.cost_microdollars + EXCLUDED.cost_microdollars
        """,
        datetime.now(UTC).date(),
        hash_ip(ip),
        pool,
        cost_microdollars,
    )
