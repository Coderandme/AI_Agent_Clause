"""Spend caps and IP extraction.

These guard real money. "The caps work" is not something to take on faith — a rate limit that
silently does nothing looks exactly like a rate limit that works, right up until the bill arrives.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from clause import guard
from clause.config import settings

# ── IP extraction ────────────────────────────────────────────────────────────────────────────────
#
# Behind Hugging Face's proxy, request.client.host is the PROXY. Every visitor looks like the same
# person, and the per-IP cap either applies to all of them at once or to none of them. The real
# address is in X-Forwarded-For.


@dataclass
class FakeClient:
    host: str


@dataclass
class FakeRequest:
    headers: dict[str, str]
    client: FakeClient | None = None


def test_takes_the_forwarded_address_not_the_proxy() -> None:
    req = FakeRequest(headers={"x-forwarded-for": "203.0.113.7"}, client=FakeClient("10.0.0.1"))
    assert guard_ip(req) == "203.0.113.7"


def test_ignores_a_forged_leading_entry() -> None:
    """The attack this defends against, and the reason we read the chain from the RIGHT.

    Anyone can send `X-Forwarded-For: 1.2.3.4` with their request. Proxies APPEND to that header
    rather than replacing it, so the leftmost value is whatever the caller chose to claim. Trusting
    it means letting an attacker rotate their apparent IP on every request and defeat the cap
    entirely, for free.

    The rightmost public entry was written by infrastructure, not by the caller.
    """
    req = FakeRequest(
        headers={"x-forwarded-for": "1.2.3.4, 203.0.113.7"},  # 1.2.3.4 is the forgery
        client=FakeClient("10.0.0.1"),
    )
    assert guard_ip(req) == "203.0.113.7"


def test_skips_private_addresses_in_the_chain() -> None:
    req = FakeRequest(
        headers={"x-forwarded-for": "203.0.113.7, 10.0.0.5, 192.168.1.1"},
        client=FakeClient("10.0.0.1"),
    )
    assert guard_ip(req) == "203.0.113.7"


def test_falls_back_to_the_socket_when_there_is_no_header() -> None:
    req = FakeRequest(headers={}, client=FakeClient("198.51.100.9"))
    assert guard_ip(req) == "198.51.100.9"


def test_never_crashes_on_a_missing_request() -> None:
    """A crash here takes down the upload path. Unknown is a fine answer; a stack trace is not."""
    assert guard_ip(None) == "unknown"
    assert guard_ip(FakeRequest(headers={}, client=None)) == "unknown"


def guard_ip(request: object) -> str:
    """Imported lazily: app.py pulls in gradio, which is slow and unnecessary for the rest of the
    suite."""
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from app import client_ip

    return client_ip(request)  # type: ignore[arg-type]


# ── the hashing ──────────────────────────────────────────────────────────────────────────────────


def test_the_raw_ip_is_never_recoverable() -> None:
    """SPEC.md §7.2. A person handing their contract to a stranger's website deserves not to have
    their address in that stranger's database."""
    ip = "203.0.113.7"
    hashed = guard.hash_ip(ip)

    assert ip not in hashed
    assert len(hashed) == 32
    assert guard.hash_ip(ip) == hashed  # stable, or the rate limit does not work at all
    assert guard.hash_ip("203.0.113.8") != hashed


def test_the_secret_is_what_stops_a_rainbow_table() -> None:
    """There are only ~4 billion IPv4 addresses. A plain sha256 of every one of them is an
    afternoon's work, and would reverse the entire table. The secret is what makes that useless."""
    import hashlib

    ip = "203.0.113.7"
    assert guard.hash_ip(ip) != hashlib.sha256(ip.encode()).hexdigest()[:32]


# ── access codes ─────────────────────────────────────────────────────────────────────────────────


def test_an_empty_code_never_grants_access(monkeypatch: pytest.MonkeyPatch) -> None:
    """The dangerous default. If ACCESS_CODE is unset in the environment and a visitor submits an
    empty string, a naive `code == expected` would return True and hand every stranger the reserved
    budget."""
    settings.cache_clear()
    monkeypatch.setenv("ACCESS_CODE", "")

    assert not guard.check_access_code("")
    assert not guard.check_access_code(None)
    assert not guard.check_access_code("anything")

    settings.cache_clear()


def test_the_right_code_grants_access_and_a_wrong_one_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings.cache_clear()
    monkeypatch.setenv("ACCESS_CODE", "open-sesame")

    assert guard.check_access_code("open-sesame")
    assert guard.check_access_code("  open-sesame  ")  # a pasted code carries whitespace
    assert not guard.check_access_code("open-sesam")
    assert not guard.check_access_code("OPEN-SESAME")

    settings.cache_clear()


# ── the limits themselves ────────────────────────────────────────────────────────────────────────


def test_the_anonymous_pool_is_smaller_than_the_hard_ceiling() -> None:
    """The whole point of two pools. If the anonymous pool equalled the ceiling, a bot could drain
    the entire month's budget and the author's own demo would break with it — which is the failure
    the split exists to prevent."""
    s = settings()
    assert s.anonymous_ceiling_microdollars < s.monthly_ceiling_microdollars
    reserve = s.monthly_ceiling_microdollars - s.anonymous_ceiling_microdollars
    assert reserve > 0, "nothing is reserved; a bot can break the author's own demo"


def test_anonymous_visitors_are_capped_harder_than_code_holders() -> None:
    s = settings()
    assert s.max_pages_anonymous < s.max_pages
    assert s.max_uploads_per_session >= 1
    assert s.max_analyses_per_ip_per_day >= 1
