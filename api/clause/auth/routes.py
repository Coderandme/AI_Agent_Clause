"""Auth HTTP endpoints: sign up (with an access code), log in, and "who am I". SPEC.md §2.5.

The flow they implement:
  * POST /api/auth/signup — a prospect you gave a code to creates their account. No valid code, no
    account. On success they are logged in immediately (we return a token).
  * POST /api/auth/login  — an existing user exchanges email + password for a token.
  * GET  /api/auth/me     — the SPA calls this on load to learn who the stored token belongs to and
    how much of their grant is left.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from clause.auth import repo
from clause.auth.deps import CurrentUser
from clause.auth.repo import AuthUser, EmailTaken, InvalidCode
from clause.auth.schemas import LoginRequest, SignupRequest, TokenResponse, UserOut
from clause.auth.security import hash_password, issue_token, verify_password
from clause.db import pool

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user: AuthUser, uploads_used: int) -> UserOut:
    remaining = None if user.is_admin else max(0, user.upload_grant - uploads_used)
    return UserOut(
        id=user.id,
        email=user.email,
        is_admin=user.is_admin,
        upload_grant=user.upload_grant,
        uploads_used=uploads_used,
        uploads_remaining=remaining,
    )


def _token_response(user: AuthUser, uploads_used: int) -> TokenResponse:
    return TokenResponse(
        access_token=issue_token(user_id=user.id, is_admin=user.is_admin),
        user=_user_out(user, uploads_used),
    )


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: SignupRequest) -> TokenResponse:
    password_hash = hash_password(body.password)

    p = await pool.pool()
    async with p.acquire() as conn:
        try:
            user = await repo.create_user_with_code(
                conn, email=body.email, password_hash=password_hash, code=body.access_code
            )
        except InvalidCode as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="That access code is not valid, or has already been used.",
            ) from exc
        except EmailTaken as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with that email already exists. Try logging in.",
            ) from exc

    # A brand-new account has used none of its grant.
    return _token_response(user, uploads_used=0)


@router.post("/login")
async def login(body: LoginRequest) -> TokenResponse:
    p = await pool.pool()
    async with p.acquire() as conn:
        user = await repo.get_user_by_email(conn, body.email)
        # Same response whether the email is unknown or the password is wrong — revealing which one
        # was correct would let an attacker enumerate who has an account. We still run the hash
        # verification on a dummy-free path only when the user exists; the tiny timing difference is
        # not a meaningful threat for this product.
        if user is None or not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
            )
        uploads_used = await repo.count_user_uploads(conn, user.id)

    return _token_response(user, uploads_used)


@router.get("/me")
async def me(user: CurrentUser) -> UserOut:
    p = await pool.pool()
    async with p.acquire() as conn:
        uploads_used = await repo.count_user_uploads(conn, user.id)
    return _user_out(user, uploads_used)
