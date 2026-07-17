"""Mint access codes and promote admins — the little management tool behind invite-only access.
SPEC.md §2.5, ROADMAP.md §8.

There is no self-serve path to a spending account: you hand people codes. This is what makes them.
It is deliberately a thin CLI over a couple of INSERTs — a code-generation screen in the app is a
nice-to-have, explicitly not part of V1 (ROADMAP.md §8).

    uv run python -m clause.auth.codes new --grant 3             # one code worth 3 analyses
    uv run python -m clause.auth.codes new --grant 3 --count 5   # five such codes
    uv run python -m clause.auth.codes list                      # codes and who claimed them
    uv run python -m clause.auth.codes make-admin you@email.com   # unlimited access for one user

Run it in the project's environment so it reads the same .env the app does:
    cd api && uv run python -m clause.auth.codes ...
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys

import asyncpg

from clause.config import settings


async def _connect() -> asyncpg.Connection:
    # A one-shot connection, not the app's pool — this is a short-lived script, not a server.
    return await asyncpg.connect(settings().database_url)


def _generate_code() -> str:
    """A short, readable code to paste into an email, e.g. 'CLAUSE-1A2B-3C4D'. Hex only, so there is
    no 0/O or 1/l ambiguity when someone types it by hand."""
    return "CLAUSE-" + "-".join(secrets.token_hex(2).upper() for _ in range(2))


async def new_codes(grant: int, count: int) -> list[str]:
    conn = await _connect()
    try:
        made: list[str] = []
        for _ in range(count):
            code = _generate_code()
            await conn.execute(
                "INSERT INTO access_codes (code, grant_count) VALUES ($1, $2)", code, grant
            )
            made.append(code)
        return made
    finally:
        await conn.close()


async def list_codes() -> list[asyncpg.Record]:
    conn = await _connect()
    try:
        rows = await conn.fetch(
            """
            SELECT c.code, c.grant_count, c.claimed_at, u.email AS claimed_by_email
            FROM access_codes c
            LEFT JOIN users u ON u.id = c.claimed_by
            ORDER BY c.created_at DESC
            """
        )
        return list(rows)
    finally:
        await conn.close()


async def make_admin(email: str) -> bool:
    conn = await _connect()
    try:
        result = await conn.execute(
            "UPDATE users SET is_admin = true WHERE email_ci = lower($1)", email
        )
        # asyncpg returns e.g. "UPDATE 1"; the trailing number is the row count.
        return str(result).rsplit(" ", 1)[-1] != "0"
    finally:
        await conn.close()


def _main() -> None:
    parser = argparse.ArgumentParser(prog="clause.auth.codes", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_new = sub.add_parser("new", help="mint one or more access codes")
    p_new.add_argument("--grant", type=int, required=True, help="analyses each code unlocks")
    p_new.add_argument("--count", type=int, default=1, help="how many codes to mint (default 1)")

    sub.add_parser("list", help="show all codes and who has claimed them")

    p_admin = sub.add_parser("make-admin", help="grant a user unlimited access")
    p_admin.add_argument("email", help="the email of an existing account")

    args = parser.parse_args()

    if args.command == "new":
        codes = asyncio.run(new_codes(args.grant, args.count))
        print(f"Minted {len(codes)} code(s), each worth {args.grant} analyses:\n")
        for c in codes:
            print(f"  {c}")
    elif args.command == "list":
        rows = asyncio.run(list_codes())
        if not rows:
            print("No access codes yet. Mint one with:  ... codes new --grant 3")
            return
        for r in rows:
            who = r["claimed_by_email"] or "(unclaimed)"
            print(f"  {r['code']}   grant={r['grant_count']}   {who}")
    elif args.command == "make-admin":
        ok = asyncio.run(make_admin(args.email))
        print(f"{args.email} is now an admin." if ok else f"No account found for {args.email}.")


if __name__ == "__main__":
    # asyncpg is happiest on the selector event loop on Windows.
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    _main()
