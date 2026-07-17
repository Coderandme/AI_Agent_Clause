"""Unit tests for the auth primitives — hashing and tokens. SPEC.md §2.5.

These are pure and need no database: they exercise the two things that, if wrong, break auth
silently rather than loudly. A password check that always returns True, or a token whose expiry is
never enforced, would both pass a happy-path click-through and fail nobody until it mattered.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from clause.auth.security import (
    InvalidToken,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)
from clause.config import settings

# ── Passwords ─────────────────────────────────────────────────────────────────────────────────────


def test_password_round_trips() -> None:
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)


def test_wrong_password_is_rejected() -> None:
    h = hash_password("correct horse battery staple")
    assert not verify_password("Correct Horse Battery Staple", h)


def test_hash_is_not_the_password() -> None:
    # The plaintext must never appear in what we store.
    h = hash_password("hunter2hunter2")
    assert "hunter2" not in h


def test_each_hash_is_salted() -> None:
    # Same password, two hashes — they must differ, or a stolen table reveals repeated passwords.
    assert hash_password("same-password-1") != hash_password("same-password-1")


def test_long_password_is_not_truncated_at_72_bytes() -> None:
    # bcrypt ignores bytes past 72; our SHA-256 pre-hash removes that. Two long passwords sharing a
    # 72-byte prefix must NOT verify against each other's hash.
    base = "A" * 72
    h = hash_password(base + "first-tail")
    assert not verify_password(base + "second-tail", h)
    assert verify_password(base + "first-tail", h)


# ── Tokens ────────────────────────────────────────────────────────────────────────────────────────


def test_token_round_trips_identity_and_admin_flag() -> None:
    uid = uuid4()
    claims = decode_token(issue_token(user_id=uid, is_admin=True))
    assert claims.user_id == uid
    assert claims.is_admin is True


def test_non_admin_flag_survives() -> None:
    claims = decode_token(issue_token(user_id=uuid4(), is_admin=False))
    assert claims.is_admin is False


def test_expired_token_is_rejected() -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid4()), "admin": False, "exp": int(past.timestamp())},
        settings().jwt_secret,
        algorithm=settings().jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        decode_token(token)


def test_token_signed_with_wrong_secret_is_rejected() -> None:
    forged = jwt.encode(
        {"sub": str(uuid4()), "admin": True, "exp": 9_999_999_999},
        "not-the-real-secret",
        algorithm=settings().jwt_algorithm,
    )
    with pytest.raises(InvalidToken):
        decode_token(forged)


def test_garbage_is_rejected() -> None:
    with pytest.raises(InvalidToken):
        decode_token("this.is.not.a.jwt")
