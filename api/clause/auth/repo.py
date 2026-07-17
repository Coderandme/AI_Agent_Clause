"""All the SQL auth needs, in one place. SPEC.md §2.5.

No ORM, matching the rest of the project (db/pool.py explains why). Rows are mapped into a small
typed AuthUser so callers get real attributes and mypy can check them, rather than passing dict-like
asyncpg Records around.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg


@dataclass(frozen=True, slots=True)
class AuthUser:
    id: UUID
    email: str
    password_hash: str
    is_admin: bool
    upload_grant: int


class EmailTaken(Exception):
    """Signup with an email that already has an account."""


class InvalidCode(Exception):
    """The access code does not exist, or has already been claimed by someone else."""


def _to_user(row: asyncpg.Record) -> AuthUser:
    return AuthUser(
        id=row["id"],
        email=row["email"],
        password_hash=row["password_hash"],
        is_admin=row["is_admin"],
        upload_grant=row["upload_grant"],
    )


async def get_user_by_email(conn: asyncpg.Connection, email: str) -> AuthUser | None:
    row = await conn.fetchrow(
        """
        SELECT id, email, password_hash, is_admin, upload_grant
        FROM users WHERE email_ci = lower($1)
        """,
        email,
    )
    return _to_user(row) if row else None


async def get_user_by_id(conn: asyncpg.Connection, user_id: UUID) -> AuthUser | None:
    row = await conn.fetchrow(
        """
        SELECT id, email, password_hash, is_admin, upload_grant
        FROM users WHERE id = $1
        """,
        user_id,
    )
    return _to_user(row) if row else None


async def count_user_uploads(conn: asyncpg.Connection, user_id: UUID) -> int:
    """How many analyses this user has consumed — the number the grant is measured against.

    This reads a COUNTER (`users.uploads_used`), incremented by ingest when a document is created.
    It deliberately does NOT count rows in `documents`, even though that would be drift-proof: the
    24-hour deletion job (retention.py) deletes those rows, so counting them would refund everyone's
    grant every night and make the cap meaningless (migration 005 has the full reasoning).

    Re-uploading the same file does not charge twice — ingest dedupes on sha256 and never reaches
    the increment.
    """
    n = await conn.fetchval("SELECT uploads_used FROM users WHERE id = $1", user_id)
    return int(n or 0)


async def create_user_with_code(
    conn: asyncpg.Connection, *, email: str, password_hash: str, code: str
) -> AuthUser:
    """Redeem a code and create the account it unlocks, atomically. SPEC.md §2.5.

    Either the whole thing happens — the code is consumed AND the user exists with the code's
    grant — or none of it does. Doing it in one transaction is what stops two people racing on the
    last use of a code, or a code being burned by a signup that then fails on a duplicate email.
    """
    async with conn.transaction():
        # Lock the code row so a concurrent signup can't claim the same one. FOR UPDATE blocks a
        # second transaction on this exact code until this one commits, serialising the redemption.
        code_row = await conn.fetchrow(
            """
            SELECT code, grant_count FROM access_codes
            WHERE code = $1 AND claimed_by IS NULL
            FOR UPDATE
            """,
            code.strip(),
        )
        if code_row is None:
            raise InvalidCode(code)

        user_id = uuid4()
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (id, email, password_hash, is_admin, upload_grant)
                VALUES ($1, $2, $3, false, $4)
                RETURNING id, email, password_hash, is_admin, upload_grant
                """,
                user_id,
                email,
                password_hash,
                code_row["grant_count"],
            )
        except asyncpg.UniqueViolationError as exc:
            # The email_ci unique index fired — someone already has this address.
            raise EmailTaken(email) from exc

        await conn.execute(
            "UPDATE access_codes SET claimed_by = $1, claimed_at = now() WHERE code = $2",
            user_id,
            code_row["code"],
        )
        assert row is not None
        return _to_user(row)
