"""Settings, loaded from the environment. Nothing here is ever interpolated into a prompt."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root — api/clause/config.py -> api/clause -> api -> repo
REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "rules" / "v1.yaml"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = ""

    database_url: str = "postgresql://clause:clause@localhost:5432/clause"

    # ── Auth (SPEC.md §2.5) ──────────────────────────────────────────────────────────────────────
    # The signing key for JWTs. A token is only as trustworthy as this secret: anyone who has it
    # can mint a token for any user, including an admin. The default is unusable on purpose —
    # override it in .env with a long random string. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: str = "dev-only-change-me-this-is-not-a-secret"
    jwt_algorithm: str = "HS256"
    # How long a login lasts before the user must sign in again. Short-lived by design; there is no
    # refresh-token flow in the MVP (SPEC.md §2.5), so this is the whole session length. A week
    # keeps a portfolio demo from logging people out mid-review without being a real exposure here.
    access_token_ttl_minutes: int = 60 * 24 * 7

    # Extra origins allowed to call this API from a browser, on top of the local Vite dev server
    # (app.py). Set this to the deployed SPA's origin, e.g. CORS_EXTRA_ORIGINS=["https://clause.vercel.app"]
    # Deliberately a list of exact origins and never "*": this API carries the token that gates
    # spending, and a wildcard would let any page on the internet call it with a victim's token.
    cors_extra_origins: list[str] = []

    # Cloudflare R2, S3-compatible. When these are unset, storage falls back to local disk — which
    # is what lets ingest be built and tested before the bucket exists. See ingest/storage.py.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "clause-documents"

    # SPEC.md §7.2 and clause/guard.py. Per-document limits on an upload.
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_pages: int = 40

    # The hard ceiling. Nothing crosses it, invited or admin. It is the backstop BEHIND the real
    # control, which is the per-account grant in auth/deps.py — access is invite-only (SPEC.md
    # §2.5), so only people the admin gave a code to can spend anything at all.
    #
    # NOTE: this only bites once an analysis records its cost via guard.record_spend, which is not
    # wired to the web path yet. See the note at the bottom of guard.py's docstring.
    monthly_ceiling_microdollars: int = 5_000_000  # $5.00

    # HMAC secret for hashing IPs in the spend ledger. The raw IP is never stored anywhere.
    # Override in production.
    ip_hash_secret: str = "dev-only-not-a-secret"

    # A scanned PDF yields no text to analyse, because we pass extracted text and not page images
    # (SPEC.md §3.2). Below this many characters per page we reject at upload with an honest message
    # rather than producing an empty analysis.
    min_chars_per_page: int = 100

    # How often the retention sweep runs (clause/retention.py). Not a tight poll on purpose: Neon
    # meters compute-hours and suspends when idle, so anything touching Postgres on a timer keeps it
    # awake (ROADMAP.md §5.1). Hourly deletes a file within an hour of its deadline for a couple of
    # compute-hours a day. Set to 0 to disable the in-process loop (e.g. if a cron calls the CLI).
    retention_sweep_minutes: int = 60

    # Uploaded documents and every row derived from them are deleted this long after upload. Stated
    # inline on the dropzone, because that is the sentence a person wants to read before handing a
    # contract to a stranger's website.
    upload_ttl_hours: int = 24


@lru_cache
def settings() -> Settings:
    return Settings()
