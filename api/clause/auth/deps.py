"""FastAPI dependencies that turn a request's `Authorization: Bearer <jwt>` header into a user, and
the gate that decides whether that user may spend money on an analysis. SPEC.md §2.5, §7.2.

A "dependency" here is a function FastAPI runs before the handler; if it raises, the handler never
runs. `current_user` is how a route says "you must be logged in", and `require_admin` "you must be
an admin", just by listing them as parameters.
"""

from __future__ import annotations

from typing import Annotated

import asyncpg
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from clause import guard
from clause.auth import repo
from clause.auth.repo import AuthUser
from clause.auth.security import InvalidToken, decode_token
from clause.config import settings
from clause.db import pool

# auto_error=False: we want to raise our OWN 401 with a clean message, not FastAPI's default.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Sign in to do that.",
    headers={"WWW-Authenticate": "Bearer"},
)


async def current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> AuthUser:
    """Resolve the caller from their token, or 401. The token is verified cryptographically first
    (cheap, no I/O); only then do we hit the database to confirm the user still exists."""
    if creds is None:
        raise _UNAUTHENTICATED
    try:
        claims = decode_token(creds.credentials)
    except InvalidToken as exc:
        raise _UNAUTHENTICATED from exc

    p = await pool.pool()
    async with p.acquire() as conn:
        user = await repo.get_user_by_id(conn, claims.user_id)
    if user is None:
        # Valid signature, but the account was deleted since the token was issued.
        raise _UNAUTHENTICATED
    return user


CurrentUser = Annotated[AuthUser, Depends(current_user)]


async def require_admin(user: CurrentUser) -> AuthUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins only.")
    return user


async def assert_can_upload(conn: asyncpg.Connection, user: AuthUser) -> None:
    """The invite-only spend gate. SPEC.md §2.5, §7.2. Raises if this user may not run an analysis.

    Two independent limits, checked BEFORE any money is spent:
      1. The per-account grant — a non-admin may run up to `upload_grant` analyses, ever. Admins are
         exempt.
      2. The hard global monthly ceiling — nothing crosses it, admin or not. It is the ultimate
         backstop even against invited clients.
    """
    # 1. Per-account grant (admins skip this).
    if not user.is_admin:
        used = await repo.count_user_uploads(conn, user.id)
        if used >= user.upload_grant:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"You've used your {user.upload_grant} "
                    f"{'analysis' if user.upload_grant == 1 else 'analyses'}. "
                    "Contact the admin for more access."
                ),
            )

    # 2. The hard global ceiling.
    total = await guard.month_spend_microdollars(conn)
    if total >= settings().monthly_ceiling_microdollars:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "This month's analysis budget is spent. The sample contracts still work — they are "
                "pre-computed and cost nothing to view."
            ),
        )
