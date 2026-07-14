"""The risk rule library: loading, validation, and the version hash.

SPEC.md §4.7. The library is a data file (rules/v1.yaml), not code. Adding a rule is a pull request
that touches YAML and the eval fixtures, and nothing else.

Two things here are load-bearing beyond mere loading:

1. `library_version()` hashes the file into `analyses.rule_library_version`, so that an analysis run
   six months ago remains explicable after the rules have moved on.

2. `index_for_prompt()` renders ONLY rule names and one-line summaries. The full detail is fetched
   on demand by the get_rule_detail tool. That keeps the cached prompt prefix small (SPEC.md §4.2)
   — and, more importantly, it means editing a rule's detection_guidance does NOT invalidate the
   prompt cache, because the guidance never appears in the prefix.
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from functools import lru_cache
from typing import Literal

import yaml
from pydantic import BaseModel

from clause.config import RULES_PATH

Severity = Literal["critical", "high", "medium", "low"]


class Family(StrEnum):
    """Rule families. Each is one pass of the risk scan, sharing the cached document prefix and
    varying only the trailing instruction (SPEC.md §4.2, §4.7)."""

    LIABILITY = "LIABILITY"
    TERMINATION = "TERMINATION"
    COMMERCIAL = "COMMERCIAL"
    RIGHTS_AND_DATA = "RIGHTS_AND_DATA"


class Rule(BaseModel):
    id: str
    family: Family
    title: str
    default_severity: Severity
    exposure: str  # user-facing prose
    detection_guidance: str  # agent-facing; returned by get_rule_detail, never in the prefix
    recommended_redline: str
    applies_to: list[str]


class RuleLibrary(BaseModel):
    version: int
    families: dict[Family, str]
    rules: list[Rule]

    def by_id(self, rule_id: str) -> Rule | None:
        return next((r for r in self.rules if r.id == rule_id), None)

    def by_family(self, family: Family) -> list[Rule]:
        return [r for r in self.rules if r.family is family]

    def index_for_prompt(self) -> str:
        """Names and one-line summaries only — this is what goes into the frozen system prompt.

        Sorted by id so the rendering is deterministic. A dict iteration order change here would
        silently invalidate the prompt cache and cost ~10x on input with no error anywhere
        (SPEC.md §4.2).
        """
        lines = [
            f"- {r.id} [{r.family}, default {r.default_severity}]: {r.title}"
            for r in sorted(self.rules, key=lambda r: r.id)
        ]
        return "\n".join(lines)


@lru_cache
def load() -> RuleLibrary:
    lib = RuleLibrary.model_validate(yaml.safe_load(RULES_PATH.read_text(encoding="utf-8")))

    ids = [r.id for r in lib.rules]
    if len(ids) != len(set(ids)):
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate rule ids in {RULES_PATH.name}: {dupes}")

    # rule_id is an enum in the record_finding tool schema (strict: true), so an empty family would
    # mean a scan pass with nothing to look for. Fail at boot, not at turn nineteen.
    for family in Family:
        if not lib.by_family(family):
            raise ValueError(f"rule family {family} has no rules")

    return lib


@lru_cache
def library_version() -> str:
    """Short content hash of the rule library, recorded on every analysis."""
    return hashlib.sha256(RULES_PATH.read_bytes()).hexdigest()[:12]


@lru_cache
def rule_ids() -> tuple[str, ...]:
    """The enum for record_finding.rule_id and note_absence.rule_id.

    Sorted, and derived from the YAML rather than duplicated in Python, so the tool schema can never
    drift from the rule library. Sorting matters beyond tidiness: tool definitions sit inside the
    cached prompt prefix, and a non-deterministic ordering here would silently invalidate the cache
    on every boot (SPEC.md §4.2).
    """
    return tuple(sorted(r.id for r in load().rules))
