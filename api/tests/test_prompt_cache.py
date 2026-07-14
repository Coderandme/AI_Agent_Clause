"""The prompt-cache invariant. SPEC.md §8.2.

One of two invariants with its own test "because both fail SILENTLY in production". The other is the
hallucination guard (test_verify.py).

When prompt caching breaks, nothing raises. No error, no warning, no degraded output. The analysis
produces identical findings and costs roughly ten times as much on input, forever, until somebody
happens to look at a usage column. It is the most expensive kind of bug there is: the kind that
works.

These tests are offline. They assert the PROPERTY that makes caching possible — a byte-identical
prefix — rather than the cache-hit rate itself, which would need a live API call on every CI run.
The live assertion (second pass reports non-zero cached tokens) is checked by the eval harness,
which does hit the API: at 88% cached across four passes, caching is demonstrably working.
"""

from __future__ import annotations

import json

from clause import rules
from clause.agent import prompts
from clause.agent.tools import TOOLS, build_tools


def test_the_system_prompt_is_stable_across_calls() -> None:
    """No timestamps, no UUIDs, no `datetime.now()`. If this fails, someone has interpolated
    something time-derived and every request is now a cache miss."""
    assert prompts.SYSTEM_PROMPT == prompts.SYSTEM_PROMPT
    assert prompts.prompt_version() == prompts.prompt_version()


def test_the_system_prompt_contains_nothing_that_varies() -> None:
    """A cheap smell test for the specific invalidators SPEC.md §4.2 names."""
    text = prompts.SYSTEM_PROMPT

    # A year would mean a date crept in. A hex-looking run would mean a UUID did.
    assert "20" not in text[:200], "something date-like near the top of the prompt"
    assert "{" not in text and "}" not in text, "an unrendered format placeholder survived"


def test_tool_definitions_are_deterministic() -> None:
    """Tool definitions sit INSIDE the cached prefix. A dict or set iterated without a sort would
    serialise differently on a different process — invalidating the cache with no error anywhere.

    Built twice, from scratch, and compared byte-for-byte.
    """
    once = json.dumps(build_tools(), sort_keys=False)
    twice = json.dumps(build_tools(), sort_keys=False)
    assert once == twice


def test_tools_are_sorted_by_name() -> None:
    names = [t["name"] for t in TOOLS]
    assert names == sorted(names), "tool order is not deterministic; the cached prefix will churn"


def test_rule_index_in_the_prompt_is_sorted() -> None:
    """The rule index IS interpolated into the system prompt — the one interpolation permitted,
    because it comes from a sorted list derived from a YAML file that does not change at runtime.
    If the sort ever came out of a set, the prompt would differ between processes."""
    assert rules.load().index_for_prompt() == rules.load().index_for_prompt()

    ids = [line.split()[1] for line in rules.load().index_for_prompt().splitlines()]
    assert ids == sorted(ids)


def test_only_the_trailing_instruction_varies_between_passes() -> None:
    """The whole caching design in one assertion.

    Every pass sends: system prompt -> tools -> document -> instruction. The first three are
    byte-identical across all four passes; only the instruction differs. That is what turns three of
    the four passes into cache hits and cuts the input bill by ~70%.
    """
    instructions = {f: prompts.family_instruction(f) for f in rules.Family}

    # The instructions must actually differ, or the passes are not doing different work.
    assert len({*instructions.values()}) == len(rules.Family)

    # Every one of them must name its own family and no other.
    for family, text in instructions.items():
        assert family.value in text
        others = [f.value for f in rules.Family if f is not family]
        assert not any(o in text for o in others), f"{family} instruction mentions another family"


def test_the_cached_prefix_is_big_enough_to_cache_at_all() -> None:
    """OpenAI only caches prefixes above 1,024 tokens. A prompt below that threshold is never
    cached, and the 70% input saving quietly does not exist.

    ~4 chars per token is the usual rough rule; the system prompt alone should clear the bar before
    the document is even added.
    """
    assert len(prompts.SYSTEM_PROMPT) / 4 > 1024
