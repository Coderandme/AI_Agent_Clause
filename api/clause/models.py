"""Model IDs, tiering, and pricing. The ONLY place in the codebase where a model ID appears.

SPEC.md §3.2: "Model IDs live in one config module, never as string literals. Pin them from the
current API reference at M0. Do not copy them from this document — the tiers move faster than
specs do."

Pinned 2026-07-14 against GET /v1/models and the live pricing page. Every ID below was confirmed
to exist on the project's own API key, and every price was read off the pricing page that day.

Re-verify before launch. If you are reading this more than a few months later, assume it is stale.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Task(StrEnum):
    """What we are asking a model to do. Tiering is per-task — see SPEC.md §3.2."""

    RISK_SCAN = "risk_scan"
    KEY_TERMS = "key_terms"
    QA = "qa"
    MEMO_SUMMARY = "memo_summary"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    """A model and what it costs. Prices are USD per million tokens, standard tier."""

    id: str
    input_per_mtok: float
    cached_input_per_mtok: float
    output_per_mtok: float

    def cost_microdollars(
        self, *, input_tokens: int, cached_input_tokens: int, output_tokens: int
    ) -> int:
        """Cost of one call, in microdollars, for the `analyses.cost_microdollars` column.

        `cached_input_tokens` is the CACHED SUBSET of `input_tokens`, not a separate bucket — that
        is how OpenAI reports it. Billing both at full rate would overstate a cached pass by ~10x
        and quietly make prompt caching look worthless in our own metrics.
        """
        uncached = input_tokens - cached_input_tokens
        if uncached < 0:
            raise ValueError(
                f"cached_input_tokens ({cached_input_tokens}) exceeds "
                f"input_tokens ({input_tokens}); check the usage adapter"
            )
        dollars = (
            uncached * self.input_per_mtok
            + cached_input_tokens * self.cached_input_per_mtok
            + output_tokens * self.output_per_mtok
        ) / 1_000_000
        return round(dollars * 1_000_000)


# ── The registry ────────────────────────────────────────────────────────────────────────────────
# Confirmed present on GET /v1/models, 2026-07-14.

SOL = ModelSpec("gpt-5.6-sol", 5.00, 0.50, 30.00)
TERRA = ModelSpec("gpt-5.6-terra", 2.50, 0.25, 15.00)
LUNA = ModelSpec("gpt-5.6-luna", 1.00, 0.10, 6.00)
MINI = ModelSpec("gpt-5.4-mini", 0.75, 0.075, 4.50)
NANO = ModelSpec("gpt-5.4-nano", 0.20, 0.02, 1.25)


# ── The tiering ─────────────────────────────────────────────────────────────────────────────────
# SPEC.md §3.2. The reasoning, in one line: output tokens dominate the bill, and caching does
# nothing about them — so spend on the flagship only where its output is visible to a human.
#
# RISK_SCAN is the demo. It is the only place quality is legible to a prospective client, and it is
# one call per document. Everything else fills a table, answers a narrow question, or writes three
# paragraphs into a Jinja template, and mini does that at 1/7th the price.
#
# RISK_SCAN's value here is PROVISIONAL. SPEC.md §8.1 fixes it by measurement at the end of V1:
#
#     "Take the cheapest tier that holds recall (critical + high) >= 0.80 and precision >= 0.75."
#
# The sweep runs sol / terra / mini and the decision rule is stated in advance so it cannot be
# rationalised afterwards. If mini holds, the scan gets ~5x cheaper and this line changes to MINI.

TIERING: dict[Task, ModelSpec] = {
    Task.RISK_SCAN: SOL,
    Task.KEY_TERMS: MINI,
    Task.QA: MINI,
    Task.MEMO_SUMMARY: MINI,
}

# The tiers the §8.1 sweep runs the risk scan at, cheapest last so the table reads left-to-right in
# descending cost.
#
# NANO is in here because it was proposed on the grounds that it is cheap, and the right response to
# "surely the cheap one is good enough" is not an argument, it is a column. It is 25x cheaper than
# SOL on input and 24x on output. My expectation is that it fails the recall gate on the risk scan,
# because the scan is a reasoning task — the finding that matters most in the sample MSA is that
# §14.2 lifts the indemnity out of the §9 liability cap, five pages away, and noticing that is
# exactly what small models are worst at. But expectations are what the sweep is for, and if NANO
# holds recall >= 0.80 then the scan gets 25x cheaper and that is a far better README section than
# anything I would have written about being right.
SWEEP_TIERS: tuple[ModelSpec, ...] = (SOL, TERRA, LUNA, MINI, NANO)

# Embeddings are local — fastembed / BAAI/bge-small-en-v1.5, 384-dim, ONNX. Zero marginal cost and
# no API key. See SPEC.md §3.3, and note that cost is explicitly NOT the reason for that choice.
# Lands in V2; the risk scan does not use retrieval (SPEC.md §4.1).
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


def for_task(task: Task) -> ModelSpec:
    return TIERING[task]
