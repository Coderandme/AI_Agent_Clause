"""Spend ledger, IP extraction, and IP hashing. SPEC.md §7.2.

These guard real money. "The caps work" is not something to take on faith — a rate limit that
silently does nothing looks exactly like a rate limit that works, right up until the bill arrives.

What is deliberately NOT tested here any more: the anonymous spend pool and the shared access code.
Both were removed on 2026-07-15 when access became invite-only (SPEC.md §2.5) — anonymous visitors
now see only the pre-computed demo, which costs nothing, so there is no anonymous spend to meter.
The real gate is the per-account grant, tested in `test_auth.py` and end-to-end against the API.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from clause import guard
from clause.config import settings

# ── IP extraction ────────────────────────────────────────────────────────────────────────────────
#
# Behind a proxy, request.client.host is the PROXY. Every visitor looks like the same person. The
# real address is in X-Forwarded-For.


@dataclass
class FakeClient:
    host: str


@dataclass
class FakeRequest:
    headers: dict[str, str]
    client: FakeClient | None = None


def test_takes_the_forwarded_address_not_the_proxy() -> None:
    req = FakeRequest(headers={"x-forwarded-for": "203.0.113.7"}, client=FakeClient("10.0.0.1"))
    assert guard.client_ip(req) == "203.0.113.7"


def test_ignores_a_forged_leading_entry() -> None:
    """The attack this defends against, and the reason we read the chain from the RIGHT.

    Anyone can send `X-Forwarded-For: 1.2.3.4` with their request. Proxies APPEND to that header
    rather than replacing it, so the leftmost value is whatever the caller chose to claim. Trusting
    it means letting an attacker rotate their apparent IP on every request.

    The rightmost public entry was written by infrastructure, not by the caller.
    """
    req = FakeRequest(
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},  # 1.2.3.4 is the forgery
        client=FakeClient("10.0.0.1"),
    )
    assert guard.client_ip(req) == "203.0.113.7"


def test_skips_private_addresses_in_the_chain() -> None:
    req = FakeRequest(
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.5, 192.168.1.1"},
        client=FakeClient("10.0.0.1"),
    )
    assert guard.client_ip(req) == "203.0.113.7"


def test_falls_back_to_the_socket_when_there_is_no_header() -> None:
    req = FakeRequest(headers={}, client=FakeClient("198.51.100.9"))
    assert guard.client_ip(req) == "198.51.100.9"


def test_never_crashes_on_a_missing_request() -> None:
    """A crash here takes down the upload path. Unknown is a fine answer; a stack trace is not."""
    assert guard.client_ip(None) == "unknown"
    assert guard.client_ip(FakeRequest(headers={}, client=None)) == "unknown"


# ── the hashing ──────────────────────────────────────────────────────────────────────────────────


def test_the_raw_ip_is_never_recoverable() -> None:
    """SPEC.md §7.2. A person handing their contract to a stranger's website deserves not to have
    their address in that stranger's database."""
    ip = "203.0.113.7"
    hashed = guard.hash_ip(ip)

    assert ip not in hashed
    assert len(hashed) == 32
    assert guard.hash_ip(ip) == hashed  # stable, or the ledger cannot aggregate at all
    assert guard.hash_ip("203.0.113.8") != hashed


def test_the_secret_is_what_stops_a_rainbow_table() -> None:
    """There are only ~4 billion IPv4 addresses. A plain sha256 of every one of them is an
    afternoon's work, and would reverse the entire table. The secret is what makes that useless."""
    ip = "203.0.113.7"
    assert guard.hash_ip(ip) != hashlib.sha256(ip.encode()).hexdigest()[:32]


# ── the ceiling ──────────────────────────────────────────────────────────────────────────────────


def test_there_is_a_hard_ceiling_and_it_is_a_real_number() -> None:
    """The backstop behind the per-account grant. It only bites once analyses record their cost via
    guard.record_spend — see the note in guard.py's docstring."""
    assert settings().monthly_ceiling_microdollars > 0
