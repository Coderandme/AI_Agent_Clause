"""The eval harness. SPEC.md §8.

    python -m clause.evals.run                    # the default tier
    python -m clause.evals.run --sweep            # §8.1: every tier, side by side

Runs the agent against the frozen corpus in evals/corpus/ and compares its output to the answer
keys in evals/labels/. Offline, deliberately: a recall number only means something when it is
compared across runs against the SAME exam, which is why the corpus is checked into git rather than
uploaded through a web page.

THE DECISION RULE, STATED IN ADVANCE (SPEC.md §8.1)
──────────────────────────────────────────────────
    Take the cheapest tier that holds recall (critical+high) >= 0.80 and precision >= 0.75.

It is written down here, before the numbers exist, so that it cannot be rationalised afterwards.
SPEC.md §8.1 is blunt about why: "The one unacceptable outcome is choosing by intuition."
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import yaml
from openai import AsyncOpenAI

from clause import models, rules
from clause.agent import loop
from clause.agent.execute import AnalysisState, ToolExecutor
from clause.agent.verify import DocumentIndex, verify
from clause.config import REPO_ROOT, settings
from clause.ingest import parse

CORPUS = REPO_ROOT / "evals" / "corpus"
LABELS = REPO_ROOT / "evals" / "labels"

CRITICAL_HIGH = {"critical", "high"}

GREEN = "\033[32m"
RED = "\033[31m"
DIM = "\033[2m"
BOLD = "\033[1m"
OFF = "\033[0m"


@dataclass(slots=True)
class Scorecard:
    model: str
    documents: int = 0

    true_positives: int = 0
    false_negatives: int = 0
    false_positives: int = 0
    true_negatives: int = 0

    # The same four, restricted to rules the key marks critical or high. This is the gate that
    # matters: catching the dangerous things (SPEC.md §8).
    tp_high: int = 0
    fn_high: int = 0

    anchors_correct: int = 0
    anchors_total: int = 0

    quotes_attempted: int = 0
    quotes_verified: int = 0

    excluded_unsure: int = 0

    cost_microdollars: int = 0
    seconds: float = 0.0

    misses: list[str] = field(default_factory=list)
    false_alarms: list[str] = field(default_factory=list)

    # A tier that CRASHED is not a tier that scored zero, and conflating the two is how you conclude
    # a model is bad when actually your harness fell over. This happened: nano hit a transient API
    # error mid-sweep, every metric came out 0.00, cost came out $0.000, and the table showed it
    # failing the gate. Run alone, it worked fine. An eval harness that reports infrastructure
    # failure as model failure is worse than no eval harness, because you will believe it.
    errors: list[str] = field(default_factory=list)

    @property
    def crashed(self) -> bool:
        return bool(self.errors) or self.documents == 0

    @property
    def recall(self) -> float:
        d = self.true_positives + self.false_negatives
        return self.true_positives / d if d else 0.0

    @property
    def recall_high(self) -> float:
        d = self.tp_high + self.fn_high
        return self.tp_high / d if d else 0.0

    @property
    def precision(self) -> float:
        d = self.true_positives + self.false_positives
        return self.true_positives / d if d else 0.0

    @property
    def verification_rate(self) -> float:
        return self.quotes_verified / self.quotes_attempted if self.quotes_attempted else 0.0

    @property
    def anchor_accuracy(self) -> float:
        return self.anchors_correct / self.anchors_total if self.anchors_total else 0.0

    @property
    def passes_gate(self) -> bool:
        """SPEC.md §8.1, stated before the numbers existed."""
        if self.crashed:
            return False  # and it must never be reported as a score — see `errors`
        return self.recall_high >= 0.80 and self.precision >= 0.75


async def score_document(
    client: AsyncOpenAI, slug: str, spec: models.ModelSpec, card: Scorecard
) -> None:
    pdf = CORPUS / f"{slug}.pdf"
    key = yaml.safe_load((LABELS / f"{slug}.yaml").read_text(encoding="utf-8"))

    doc = parse.parse(pdf.read_bytes())
    index = DocumentIndex(
        doc.full_text, [(p.page_number, p.char_start, p.char_end) for p in doc.pages]
    )

    state = AnalysisState()
    execute = ToolExecutor(index, state)

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        return None

    started = time.monotonic()

    async def run(family: rules.Family) -> loop.PassResult:
        return await loop.run_pass(
            client,
            family=family,
            document_text=doc.full_text,
            execute_tool=execute,
            emit=emit,
            model=spec,
        )

    # Warm the cached prefix on one pass, then fan out — see analyse.py.
    families = list(rules.Family)
    first = await run(families[0])
    rest = await asyncio.gather(*(run(f) for f in families[1:]))

    usage = loop.Usage()
    for r in [first, *rest]:
        usage.input_tokens += r.usage.input_tokens
        usage.cached_input_tokens += r.usage.cached_input_tokens
        usage.output_tokens += r.usage.output_tokens

    card.seconds += time.monotonic() - started
    card.cost_microdollars += usage.cost_microdollars(spec)
    card.documents += 1

    # ── compare against the answer key ───────────────────────────────────────────────────────────
    card.quotes_attempted += len(state.findings)
    card.quotes_verified += len(state.verified_findings)

    # Only VERIFIED findings count. An unverified finding never reaches the user, so it can neither
    # earn credit for a catch nor be blamed as a false alarm — it simply does not exist.
    found = {f.rule_id: f for f in state.verified_findings}

    for entry in key["rules"]:
        rule_id = entry["rule_id"]

        # An honest "I'm not sure" in the key is excluded rather than guessed. A metric computed
        # over labels the labeller did not believe is a metric that means nothing.
        if entry.get("unsure"):
            card.excluded_unsure += 1
            continue

        should_fire = entry["fires"] is True
        did_fire = rule_id in found
        is_high = entry.get("severity") in CRITICAL_HIGH

        if should_fire and did_fire:
            card.true_positives += 1
            if is_high:
                card.tp_high += 1

            # Anchor accuracy: did the span the agent quoted actually overlap the clause the key
            # points at? Firing the right rule off the wrong sentence is not a catch.
            card.anchors_total += 1
            truth = verify(entry["clause"], index)
            f = found[rule_id]
            if (
                truth.verified
                and f.char_start is not None
                and truth.char_start is not None
                and truth.char_end is not None
                and f.char_end is not None
                and f.char_start < truth.char_end
                and truth.char_start < f.char_end
            ):
                card.anchors_correct += 1

        elif should_fire and not did_fire:
            card.false_negatives += 1
            if is_high:
                card.fn_high += 1
            card.misses.append(f"{slug}/{rule_id} ({entry.get('severity')})")

        elif not should_fire and did_fire:
            card.false_positives += 1
            card.false_alarms.append(f"{slug}/{rule_id} — {found[rule_id].title}")

        else:
            card.true_negatives += 1


async def evaluate(spec: models.ModelSpec, slugs: list[str]) -> Scorecard:
    client = AsyncOpenAI(api_key=settings().openai_api_key)
    card = Scorecard(model=spec.id)
    for slug in slugs:
        try:
            await score_document(client, slug, spec, card)
        except Exception as exc:  # noqa: BLE001 — one bad tier must not sink the whole sweep
            msg = f"{slug}: {type(exc).__name__}: {exc}"
            card.errors.append(msg)
            print(f"  {RED}ERROR  {spec.id} — {msg}{OFF}")
    return card


def print_table(cards: list[Scorecard]) -> None:
    print()
    print("═" * 100)
    print(f"{BOLD}MODEL TIER SWEEP{OFF}   SPEC.md §8.1")
    print(
        f"{DIM}Decision rule, stated in advance: take the CHEAPEST tier holding "
        f"recall(critical+high) >= 0.80 and precision >= 0.75{OFF}"
    )
    print("═" * 100)
    print()

    def col(c: Scorecard, value: str) -> str:
        """A crashed tier reports ERROR, never a number. See Scorecard.errors."""
        return "ERROR" if c.crashed else value

    rows: list[tuple[str, list[str]]] = [
        ("recall (critical+high)", [col(c, f"{c.recall_high:.2f}") for c in cards]),
        ("recall (all)", [col(c, f"{c.recall:.2f}") for c in cards]),
        ("precision", [col(c, f"{c.precision:.2f}") for c in cards]),
        ("quote verification", [col(c, f"{c.verification_rate:.2f}") for c in cards]),
        ("anchor accuracy", [col(c, f"{c.anchor_accuracy:.2f}") for c in cards]),
        ("", []),
        (
            "caught / missed",
            [col(c, f"{c.true_positives} / {c.false_negatives}") for c in cards],
        ),
        ("false alarms", [col(c, str(c.false_positives)) for c in cards]),
        ("", []),
        (
            "cost per document",
            [col(c, f"${c.cost_microdollars / max(c.documents, 1) / 1e6:.3f}") for c in cards],
        ),
        (
            "seconds per document",
            [col(c, f"{c.seconds / max(c.documents, 1):.0f}s") for c in cards],
        ),
    ]

    width = 16
    header = f"{'':<24}" + "".join(f"{c.model:>{width}}" for c in cards)
    print(BOLD + header + OFF)
    print("─" * len(header))

    for name, values in rows:
        if not name:
            print()
            continue
        print(f"{name:<24}" + "".join(f"{v:>{width}}" for v in values))

    print()
    gates = []
    for c in cards:
        if c.crashed:
            mark = f"{RED}ERROR{OFF}"
        elif c.passes_gate:
            mark = f"{GREEN}PASS{OFF}"
        else:
            mark = f"{RED}fail{OFF}"
        gates.append(f"{mark:>{width + 9}}")
    print(f"{BOLD}{'GATE':<24}{OFF}" + "".join(gates))
    print()

    if any(c.crashed for c in cards):
        print(
            f"{RED}One or more tiers did not complete.{OFF} They are reported as ERROR, not as a "
            f"score — a crashed model is not a bad model, and conflating them is how you end up "
            f"believing your harness instead of your data. Re-run before drawing conclusions.\n"
        )

    winners = [c for c in cards if c.passes_gate]
    if winners:
        # cards arrive most-expensive-first, so the last passing tier is the cheapest one.
        best = winners[-1]
        top = cards[0]
        saving = top.cost_microdollars / best.cost_microdollars if best.cost_microdollars else 1.0
        print(
            f"{BOLD}→ The rule says: choose {best.model}.{OFF} Cheapest tier holding the gate, "
            f"{saving:.1f}x cheaper than {top.model}."
        )
    else:
        print(f"{RED}No tier passes the gate.{OFF} The prompt is the problem, not the model.")

    # The most important sentence this harness prints, and the reason the recommendation above is
    # phrased as "the rule says" rather than "choose".
    #
    # SPEC.md §8 assumes ten contracts and ~70 labelled findings. Below that, a single lucky catch
    # moves recall by 0.10 and flips the gate — and it does: two consecutive runs of this sweep,
    # against the SAME contract and the SAME answer key, disagreed about which tier to pick. Recall
    # for one tier moved 1.00 -> 0.80 between runs with nothing changed but the dice.
    #
    # Run-to-run variance is currently as large as the difference between models. So the harness
    # says what the rule says, and then says this, and a human decides.
    labelled = sum(c.true_positives + c.false_negatives for c in cards[:1])
    if cards[0].documents < 5:
        print(
            f"\n{RED}{BOLD}DO NOT ACT ON THIS TABLE YET.{OFF} {cards[0].documents} document(s), "
            f"~{labelled} labelled findings. SPEC.md §8 assumes ten contracts and ~70 findings, "
            f"and it assumes that for a reason: at this sample size the run-to-run variance is as "
            f"large as the gap between models. Two consecutive runs of this sweep have already "
            f"disagreed about the winner. Label more contracts before believing the ranking."
        )

    print()
    for c in cards:
        if c.misses or c.false_alarms:
            print(f"{DIM}{c.model}{OFF}")
            for m in c.misses:
                print(f"  {RED}missed{OFF}      {m}")
            for f in c.false_alarms:
                print(f"  {RED}invented{OFF}    {f}")
    if any(c.excluded_unsure for c in cards):
        n = cards[0].excluded_unsure
        print(f"\n{DIM}{n} label(s) marked `unsure` and excluded from the metrics.{OFF}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(prog="clause.evals.run")
    ap.add_argument("--sweep", action="store_true", help="run every tier (SPEC.md §8.1)")
    args = ap.parse_args()

    slugs = sorted(p.stem for p in LABELS.glob("*.yaml"))
    if not slugs:
        print("No answer keys in evals/labels/.", file=sys.stderr)
        return 2

    tiers = list(models.SWEEP_TIERS) if args.sweep else [models.for_task(models.Task.RISK_SCAN)]

    print(f"{BOLD}corpus{OFF}  {', '.join(slugs)}")
    print(f"{BOLD}tiers {OFF}  {', '.join(t.id for t in tiers)}\n")

    async def go() -> list[Scorecard]:
        cards = []
        for spec in tiers:
            print(f"{DIM}running {spec.id}…{OFF}")
            cards.append(await evaluate(spec, slugs))
        return cards

    cards = asyncio.run(go())
    print_table(cards)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
