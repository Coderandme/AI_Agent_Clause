# Clause — the API in one container. Deployed to Render (free web service). See DEPLOY.md.
#
# ONE container: the FastAPI app, the agent, the ingest pipeline, and the retention sweep are all
# Python and all run in the same process. Postgres is Neon (free tier), reached over the network.
#
# WHY NOT HUGGING FACE, AND WHY NOT SERVERLESS. This targeted HF Spaces until July 2026, when HF
# removed the free CPU Basic flavor and paywalled the Docker SDK for unpaid accounts — the second
# host to withdraw its free tier under this project, after Fly.io (ROADMAP.md §2.3). It cannot be
# Vercel/Lambda-style serverless either, for a reason that is structural rather than about price: an
# analysis takes 40-80 seconds and runs as a background task AFTER the HTTP response is sent, and a
# serverless function is killed the moment it responds. This needs a process that keeps running.
#
# WHAT THIS SERVES, AND WHAT IT DOES NOT. This image is the BACKEND only — the JSON API. The React
# SPA is a separate static build on Vercel (ROADMAP.md §2.1); it is not compiled in here, and the
# public demo does not touch this container at all, because the demo is pre-computed JSON bundled
# into the SPA. That is deliberate: this free container sleeps after 15 minutes idle and takes ~50s
# to wake, and the demo must never wait for that.
#
# Dependencies come from api/uv.lock, so the image is reproducible.
#
# Nothing durable is stored on this container's disk: uploaded PDFs are handed to object storage, and
# the filesystem is ephemeral — a redeploy wipes it.

FROM python:3.12-slim

# PyMuPDF needs nothing exotic, but the slim image lacks the basics its wheels expect.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Run as a non-root user. Not required by Render the way it was by HF Spaces, but a container that
# does not need root should not have it.
RUN useradd -m -u 1000 app
USER app
ENV PATH="/app/api/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world. --frozen: install exactly what
# uv.lock pins and fail if it disagrees with pyproject, rather than quietly resolving something new.
COPY --chown=app api/pyproject.toml api/uv.lock ./api/
RUN cd api && uv sync --frozen --no-install-project --no-dev

COPY --chown=app api/ ./api/
COPY --chown=app rules/ ./rules/
COPY --chown=app demo/ ./demo/
COPY --chown=app README.md SPEC.md ROADMAP.md ./
RUN cd api && uv sync --frozen --no-dev

# Render assigns the port at runtime via $PORT and routes to whatever we bind. Hard-coding a port is
# how a deploy goes green and then 502s on every request. The default is only for `docker run` local.
EXPOSE 10000
CMD ["sh", "-c", "uvicorn clause.app:app --host 0.0.0.0 --port ${PORT:-10000} --app-dir /app/api"]
