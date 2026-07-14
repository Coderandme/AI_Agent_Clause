# Clause — the whole application in one container. Deployed to Hugging Face Spaces (free CPU tier).
#
# ONE container, not three. The Gradio UI, the agent, and the ingest pipeline are all Python and all
# run in the same process. There is no separate frontend build, no CORS, and no second deploy —
# which is most of why the interim Gradio UI ships today and the Next.js one does not.
#
# Postgres is Neon (free tier), reached over the network. Nothing is stored on this container's
# disk: uploaded PDFs are parsed in memory and discarded, which is both a privacy property worth
# having and a necessity, since a Spaces container's filesystem is ephemeral.

FROM python:3.12-slim

# PyMuPDF needs nothing exotic, but the slim image lacks the basics its wheels expect.
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

# HF Spaces runs the container as a non-root user with UID 1000. Files written by root at build
# time are then unreadable at runtime, which fails in ways that look like a code bug.
RUN useradd -m -u 1000 user
USER user
ENV PATH="/home/user/.local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall the world.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

COPY --chown=user api/ ./api/
COPY --chown=user rules/ ./rules/
COPY --chown=user demo/ ./demo/
COPY --chown=user evals/ ./evals/
COPY --chown=user app.py README.md SPEC.md ROADMAP.md ./

# Spaces routes to 7860 and will not negotiate about it.
EXPOSE 7860

CMD ["python", "app.py"]
