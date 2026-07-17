.PHONY: help install analyse eval sweep label test lint db clean

help:
	@echo "Clause — contract intelligence agent"
	@echo ""
	@echo "  make install    install dependencies (uv)"
	@echo "  make analyse    run the agent on the sample contract, print verified findings"
	@echo "  make eval       score the agent against the answer keys in evals/labels/"
	@echo "  make sweep      the model-tier sweep (SPEC.md 8.1) — costs ~\$$1 in API calls"
	@echo "  make test       49 tests. the ones that matter are in test_verify.py and test_auth.py"
	@echo "  make lint       ruff + mypy"
	@echo ""
	@echo "  Needs OPENAI_API_KEY and DATABASE_URL in .env"

install:
	cd api && uv sync --extra dev

# The M2 deliverable: a PDF goes in, verified findings with page numbers come out.
analyse:
	cd api && uv run python -m clause.analyse ../demo/contracts/saas_msa.pdf

# SPEC.md 8. Runs OFFLINE against the frozen corpus in evals/ and the answer keys in evals/labels/.
# A test suite, not a product feature — a recall number only means something compared across runs
# against the SAME exam.
eval:
	cd api && uv run python -m clause.evals.run

# SPEC.md 8.1. Every tier, side by side, against a decision rule stated in advance.
sweep:
	cd api && uv run python -m clause.evals.run --sweep

# Answer-key tooling. `label new <pdf>` makes a worksheet; `label check <yaml>` verifies every
# clause you quoted actually exists in the document — using the same guard the agent's quotes face.
label:
	cd api && uv run python -m clause.evals.label check ../evals/labels/salesforce_msa.yaml

test:
	cd api && uv run pytest

lint:
	cd api && uv run ruff check . && uv run ruff format --check . && uv run mypy clause

# Local Postgres + pgvector. Production is Neon; this is only for development, and only if you
# have Docker. Developing straight against a Neon branch works fine too.
db:
	docker compose up -d db

clean:
	docker compose down -v
