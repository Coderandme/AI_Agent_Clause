"""Tool execution — where the agent's tool calls actually do something.

This is where quote verification sits in the path (SPEC.md §4.5). `record_finding` cannot write a
finding without the quote being verified first, and the verification result goes straight back to
the model, so it learns immediately that it misquoted and can correct itself in the next turn.

The executor collects results in memory rather than writing to Postgres directly. That is what lets
the eval harness run the agent against ten contracts without a database, and it keeps the loop and
the persistence layer independent of each other. The caller decides what to do with the results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from clause import rules
from clause.agent.verify import DocumentIndex, verify


@dataclass(slots=True)
class Finding:
    rule_id: str
    severity: str
    title: str
    exposure: str
    recommendation: str
    quoted_text: str
    confidence: str
    # Derived by verification, never supplied by the agent.
    verified: bool
    matched_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None


@dataclass(slots=True)
class Absence:
    rule_id: str
    rationale: str


@dataclass(slots=True)
class AnalysisState:
    """What one analysis has produced so far. Accumulates across the four family passes."""

    findings: list[Finding] = field(default_factory=list)
    absences: list[Absence] = field(default_factory=list)
    key_terms: dict[str, Any] | None = None
    summaries: list[str] = field(default_factory=list)

    @property
    def verified_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.verified]

    @property
    def unverified_count(self) -> int:
        return sum(1 for f in self.findings if not f.verified)


class ToolExecutor:
    """Executes the agent's tool calls against one document."""

    def __init__(self, index: DocumentIndex, state: AnalysisState) -> None:
        self.index = index
        self.state = state
        self.library = rules.load()

    async def __call__(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_{name}", None)
        if handler is None:
            # Unknown tool. Impossible via the API (tools are declared), but the model can still
            # hallucinate a name — and this must return a result, not raise, or the loop wedges.
            return {"error": f"No such tool: {name}."}
        return await handler(args)

    async def _get_rule_detail(self, args: dict[str, Any]) -> dict[str, Any]:
        rule = self.library.by_id(args.get("rule_id", ""))
        if rule is None:
            return {"error": f"No such rule: {args.get('rule_id')!r}."}
        return {
            "rule_id": rule.id,
            "title": rule.title,
            "default_severity": rule.default_severity,
            "exposure": rule.exposure,
            "detection_guidance": rule.detection_guidance,
            "recommended_redline": rule.recommended_redline,
        }

    async def _record_finding(self, args: dict[str, Any]) -> dict[str, Any]:
        """The hallucination guard in the path. A finding cannot exist unverified."""
        quote = args.get("quoted_text", "")
        result = verify(quote, self.index)

        self.state.findings.append(
            Finding(
                rule_id=args.get("rule_id", ""),
                severity=args.get("severity", "medium"),
                title=args.get("title", ""),
                exposure=args.get("exposure", ""),
                recommendation=args.get("recommendation", ""),
                quoted_text=quote,
                confidence=args.get("confidence", "medium"),
                verified=result.verified,
                matched_text=result.matched_text,
                char_start=result.char_start,
                char_end=result.char_end,
                page_number=result.page_number,
            )
        )

        if result.verified:
            return {"verified": True, "page": result.page_number}

        # The model sees this. It is a prompt, not a log line — it has to tell the agent how to
        # recover, or the retry is just another guess.
        return {"verified": False, "reason": result.reason, "finding_discarded": True}

    async def _note_absence(self, args: dict[str, Any]) -> dict[str, Any]:
        self.state.absences.append(
            Absence(
                rule_id=args.get("rule_id", ""),
                rationale=args.get("rationale", ""),
            )
        )
        return {"recorded": True}

    async def _record_key_terms(self, args: dict[str, Any]) -> dict[str, Any]:
        self.state.key_terms = dict(args)
        return {"recorded": True}

    async def _finalize(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = args.get("summary", "")
        self.state.summaries.append(summary)
        return {"complete": True}
