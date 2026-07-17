"""The two cryptographic primitives auth rests on: password hashing and token signing. SPEC.md §2.5.

Kept in one small module with no database and no framework imports, so it can be unit-tested in
isolation and read in one sitting. Everything here is pure: bytes in, bytes out.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID

import bcrypt
import jwt

from clause.config import settings

# ── Passwords ─────────────────────────────────────────────────────────────────────────────────────
# We never store a password, only a bcrypt hash of it. bcrypt is deliberately slow, which is the
# point: it makes guessing a stolen hash expensive.
#
# bcrypt has a quirk — it silently ignores everything past the 72nd byte of a password. Two long
# passwords that share a 72-byte prefix would hash identically. We sidestep it by first running the
# password through SHA-256 and base64-encoding the digest: that is always 44 bytes, depends on the
# WHOLE password, and stays well under bcrypt's limit. (Standard practice, e.g. Django's hashers.)


def _prehash(password: str) -> bytes:
    digest = hashlib.sha256(password.encode("utf-8")).digest()
    return base64.b64encode(digest)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(_prehash(password), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(password), password_hash.encode("ascii"))
    except ValueError:
        # A malformed hash in the database is not a match — it is a corrupt row. Fail closed.
        return False


# ── Tokens ────────────────────────────────────────────────────────────────────────────────────────
# On login we hand the browser a JWT: a JSON payload (who you are, admin or not, when it expires)
# signed with our secret. The browser sends it back on every request; we verify the signature and
# trust the payload without a database lookup. There is no server-side session to store — the token
# IS the session. See config.jwt_secret for why that secret matters so much.


class InvalidToken(Exception):
    """Raised for any token we will not honour: bad signature, expired, or malformed."""


def issue_token(*, user_id: UUID, is_admin: bool) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),  # subject: the user id
        "admin": is_admin,
        "iat": int(now.timestamp()),  # issued-at
        "exp": int(  # expiry — enforced by jwt.decode below
            (now + timedelta(minutes=settings().access_token_ttl_minutes)).timestamp()
        ),
    }
    return jwt.encode(payload, settings().jwt_secret, algorithm=settings().jwt_algorithm)


class TokenClaims:
    """The trusted contents of a verified token."""

    __slots__ = ("user_id", "is_admin")

    def __init__(self, *, user_id: UUID, is_admin: bool) -> None:
        self.user_id = user_id
        self.is_admin = is_admin


def decode_token(token: str) -> TokenClaims:
    try:
        payload = jwt.decode(token, settings().jwt_secret, algorithms=[settings().jwt_algorithm])
    except jwt.InvalidTokenError as exc:  # covers expiry, bad signature, malformed
        raise InvalidToken(str(exc)) from exc

    try:
        return TokenClaims(user_id=UUID(payload["sub"]), is_admin=bool(payload["admin"]))
    except (KeyError, ValueError) as exc:
        raise InvalidToken("token payload is missing or malformed") from exc
