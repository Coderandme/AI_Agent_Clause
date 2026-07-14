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

    # Cloudflare R2, S3-compatible. When these are unset, storage falls back to local disk — which
    # is what lets ingest be built and tested before the bucket exists. See ingest/storage.py.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket: str = "clause-documents"

    # SPEC.md §7.2 and clause/guard.py. Abuse limits on a public URL.
    max_upload_bytes: int = 10 * 1024 * 1024  # 10 MB
    max_pages: int = 40
    max_analyses_per_ip_per_day: int = 3
    # Anonymous visitors only. Access-code holders are not limited per session.
    max_uploads_per_session: int = 1

    # The hard ceiling. Nothing crosses it — access code or not.
    monthly_ceiling_microdollars: int = 5_000_000  # $5.00

    # Of that $5, this much may be spent by ANONYMOUS visitors. The remainder is reserved behind the
    # access code, so that a bot draining the public pool cannot break the author's own demo on the
    # day they need it. See the module docstring in guard.py.
    anonymous_ceiling_microdollars: int = 2_000_000  # $2.00

    # Full upload access. Shared with recruiters and interviewers; empty disables the reserved pool.
    access_code: str = ""

    # HMAC secret for hashing IPs. The raw IP is never stored anywhere. Override in production.
    ip_hash_secret: str = "dev-only-not-a-secret"

    # A scanned PDF yields no text to analyse, because we pass extracted text and not page images
    # (SPEC.md §3.2). Below this many characters per page we reject at upload with an honest message
    # rather than producing an empty analysis.
    min_chars_per_page: int = 100

    # Uploaded documents and every row derived from them are deleted this long after upload. Stated
    # inline on the dropzone, because that is the sentence a person wants to read before handing a
    # contract to a stranger's website.
    upload_ttl_hours: int = 24


@lru_cache
def settings() -> Settings:
    return Settings()
