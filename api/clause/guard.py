"""The spend ledger and the hard monthly ceiling. SPEC.md §7.2.

WHO CAN SPEND MONEY, AND HOW THAT IS ENFORCED
─────────────────────────────────────────────
Access is INVITE-ONLY (SPEC.md §2.5). There is no anonymous path to an analysis:

  * Anonymous visitors see the pre-computed demo contracts. That costs **nothing** — no API call is
    made; the findings and the trace are replayed from disk. This is the default, public experience.
  * Running the agent on your OWN contract requires an account, and an account requires a single-use
    access code that the admin handed out. Each account carries an `upload_grant` — a lifetime
    number of analyses it may run.
  * Admins are unlimited.

So the set of people who can spend the admin's OpenAI budget is exactly the set of people the admin
invited. That gate lives in `auth/deps.py::assert_can_upload`, and it is checked BEFORE any analysis
runs, never after — checking afterwards is not a cap, it is a postmortem.

This module is the layer *behind* that gate: the ledger of what has been spent, and the hard global
ceiling that nothing crosses, invited or not. `assert_can_upload` reads `month_spend_microdollars`.

HISTORY, BECAUSE THIS FILE USED TO SAY SOMETHING ELSE
────────────────────────────────────────────────────
Until 2026-07-15 this module implemented a two-pool model: a small ANONYMOUS pool any stranger could
draw from, and a larger RESERVED pool behind a single shared access code. That was superseded when
the product was reframed as a portfolio tool shown to a handful of prospects rather than a public
SaaS (SPEC.md v1.3). Anonymous visitors now cost exactly zero, so there is nothing for an anonymous
pool to meter, and it has been removed rather than left to rot into a lie.

NOTE: `record_spend` has no caller yet. The analysis pipeline is not wired to the web upload path
(ROADMAP.md V1), so nothing writes to the ledger and the ceiling below cannot fire. Until that
lands, the *effective* cap is the per-account grant, which bounds spend at (codes issued x grant).
Whoever wires the analysis must call `record_spend`, or the ceiling is decoration.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import asyncpg

from clause.config import settings

# Addresses that are not the visitor: loopback, RFC1918 private ranges, IPv6 link/unique-local.
PRIVATE_PREFIXES = ("10.", "127.", "172.16.", "172.17.", "192.168.", "::1", "fc", "fd")


def client_ip(request: Any) -> str:
    """The visitor's real IP address, read from the proxy chain.

    Behind a proxy (Hugging Face, Vercel, Cloudflare), `request.client.host` is the PROXY, not the
    visitor — so every visitor looks like the same person. The real address arrives in
    `X-Forwarded-For`, a comma-separated chain appended to by each proxy it passes through:

        X-Forwarded-For: <client>, <proxy-1>, <proxy-2>

    We take the LAST entry that is not a private address, not the first. The first is the one a
    caller can forge — anyone can send their own `X-Forwarded-For: 1.2.3.4` and the proxies simply
    append to it, so trusting the leftmost value means trusting the attacker. The rightmost public
    entry was written by infrastructure we do not control but do trust more than the caller.

    Lives here rather than in a UI module so it outlives any particular frontend: it is a property
    of being behind a proxy, not of any one framework.
    """
    if request is None:
        return "unknown"

    forwarded: str = request.headers.get("x-forwarded-for", "") or ""
    candidates = [ip.strip() for ip in forwarded.split(",") if ip.strip()]
    for ip in reversed(candidates):
        if not ip.lower().startswith(PRIVATE_PREFIXES):
            return ip

    if request.client and request.client.host:
        return str(request.client.host)
    return "unknown"


def hash_ip(ip: str) -> str:
    """The raw IP is NEVER stored. Only HMAC(ip, secret) — SPEC.md §7.2.

    A person handing their contract to a stranger's website deserves not to have their address in
    that stranger's database. The secret is what stops a rainbow table: there are only ~4 billion
    IPv4 addresses, so a plain SHA-256 of every one of them is an afternoon's work.
    """
    return hmac.new(settings().ip_hash_secret.encode(), ip.encode(), hashlib.sha256).hexdigest()[
        :32
    ]


async def month_spend_microdollars(conn: asyncpg.Connection) -> int:
    """Total spent this calendar month. Read by `auth/deps.py::assert_can_upload`."""
    now = datetime.now(UTC)
    total = await conn.fetchval(
        """
        SELECT COALESCE(SUM(cost_microdollars), 0) FROM usage_ledger
        WHERE day >= date_trunc('month', $1::date)
        """,
        now.date(),
    )
    return int(total or 0)


async def record_spend(conn: asyncpg.Connection, *, ip: str, cost_microdollars: int) -> None:
    """Add one analysis's cost to the ledger. Call this AFTER an analysis completes.

    The `pool` column is a leftover of the two-pool model described above. Every analysis is now run
    by an invited account, so everything lands in 'reserved'; the column stays because dropping it
    would be a migration that buys nothing.
    """
    await conn.execute(
        """
        INSERT INTO usage_ledger (day, ip_hash, pool, analyses, cost_microdollars)
        VALUES ($1, $2, 'reserved', 1, $3)
        ON CONFLICT (day, ip_hash, pool) DO UPDATE
          SET analyses          = usage_ledger.analyses + 1,
              cost_microdollars = usage_ledger.cost_microdollars + EXCLUDED.cost_microdollars
        """,
        datetime.now(UTC).date(),
        hash_ip(ip),
        cost_microdollars,
    )
