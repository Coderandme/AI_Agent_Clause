"""The shapes that cross the auth API boundary. SPEC.md §2.5.

Pydantic validates every request against these before a handler runs, and serialises every response
through them — so a handler never sees a malformed email or accidentally returns a password hash.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class SignupRequest(BaseModel):
    email: EmailStr
    # A floor, not a policy lecture. 8 characters is the usual minimum; the cap is only there so a
    # megabyte of "password" can't be posted at the hasher.
    password: str = Field(min_length=8, max_length=128)
    # Invite-only: no valid code, no account (SPEC.md §2.5). Whitespace is stripped before lookup.
    access_code: str = Field(min_length=1)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """The public view of a user. Note what is absent: password_hash never appears here."""

    id: UUID
    email: EmailStr
    is_admin: bool
    upload_grant: int
    uploads_used: int
    # Convenience for the frontend so it doesn't recompute the rule. None means unlimited (admin).
    uploads_remaining: int | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut
