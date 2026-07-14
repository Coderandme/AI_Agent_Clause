"""The agent loop. SPEC.md §4.3.

A hand-rolled tool-use loop against the OpenAI SDK. Not LangGraph, and the reasoning is in the spec:
when an analysis wedges at turn nineteen you want to read a `for` loop and a list of messages, not
reason about how a graph checkpointer serialised its state.

Field names below are pinned against openai-python 2.45.0 by inspecting the SDK, not copied from
SPEC.md §4.3 — whose pseudocode says `response.refusal` and `response.output_text`, neither of which
exists. The spec says as much itself: "the field names above are indicative, not authoritative".
What is actually true, as of 2.45.0:

    response.output                        list of output items
    item.type                              'function_call' | 'message' | 'reasoning' | ...
    item.content[].type == 'refusal'       a refusal is a CONTENT PART, not a top-level field
    response.status                        'completed' | 'incomplete' | 'failed' | ...
    response.incomplete_details.reason     'max_output_tokens' | 'content_filter'
    response.usage.input_tokens_details.cached_tokens
    {'type': 'function_call_output', 'call_id': ..., 'output': ...}   what we send back

Three details are load-bearing regardless of naming, and all three are easy to get wrong silently:

  * Append the model's FULL output, not just extracted text. On a reasoning model, dropping the
    reasoning items forces it to re-derive its reasoning every turn — you pay for it twice and get
    worse results.
  * ONE tool-result message per tool call. This is the opposite of Anthropic's convention, where
    results batch into a single message. Getting it wrong is a validation error at best and
    silently suppresses parallel tool calls at worst.
  * A failing tool returns a result DESCRIBING the failure — never a dropped message. Every call_id
    must have a matching output or the next request is rejected outright.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from openai import AsyncOpenAI
from openai.types.responses import Response

from clause import models, rules
from clause.agent import prompts
from clause.agent.tools import TOOLS

log = logging.getLogger(__name__)

MAX_TURNS = 25


class AgentTurnLimitExceeded(Exception):
    """The agent used its whole turn budget without calling finalize. Something is wrong with the
    prompt or the model is stuck in a loop — either way, surface it rather than truncate
    silently."""


class AgentRefused(Exception):
    """The model declined the request. SPEC.md §7.4: a contract containing, say, security-testing
    scope language is a plausible trigger. Any code that reads response content without checking
    for this first will crash on it."""


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0

    def add(self, response: Response) -> None:
        u = response.usage
        if u is None:
            return
        self.input_tokens += u.input_tokens
        self.output_tokens += u.output_tokens
        if u.input_tokens_details is not None:
            self.cached_input_tokens += u.input_tokens_details.cached_tokens

    def cost_microdollars(self, spec: models.ModelSpec) -> int:
        return spec.cost_microdollars(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            output_tokens=self.output_tokens,
        )


@dataclass(slots=True)
class PassResult:
    family: rules.Family
    turns: int
    summary: str | None
    usage: Usage = field(default_factory=Usage)


# A tool executor takes (name, arguments) and returns the JSON-serialisable result the model sees.
# The agent's tools have side effects — they write findings to the database — so this is injected
# rather than imported, which is what lets the eval harness run the loop without a database.
ToolExecutor = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]

# Called for every event worth showing the user. In M3 this writes to `agent_events` and streams
# over SSE; for now the CLI prints it. The agent trace is a FEATURE, not a debug panel — watching
# the agent call get_rule_detail, then record_finding, is what makes it legibly agentic.
TraceSink = Callable[[str, dict[str, Any]], Awaitable[None]]


async def run_pass(
    client: AsyncOpenAI,
    *,
    family: rules.Family,
    document_text: str,
    execute_tool: ToolExecutor,
    emit: TraceSink,
    model: models.ModelSpec | None = None,
) -> PassResult:
    """One rule-family pass. Four of these make a scan.

    The message list is built so that everything before the trailing instruction is byte-identical
    across all four passes. That is what makes three of them cache hits (SPEC.md §4.2) — and the
    integration test asserting a non-zero cached-token count on pass two is what stops that breaking
    silently.
    """
    spec = model or models.for_task(models.Task.RISK_SCAN)
    usage = Usage()

    messages: list[Any] = [
        # ── the cached prefix ────────────────────────────────────────────────────────────────────
        {"role": "system", "content": prompts.SYSTEM_PROMPT},
        {"role": "user", "content": prompts.DOCUMENT_PREAMBLE + document_text},
        # ── varies per pass ──────────────────────────────────────────────────────────────────────
        {"role": "user", "content": prompts.family_instruction(family)},
    ]

    summary: str | None = None

    for turn in range(1, MAX_TURNS + 1):
        response = await client.responses.create(
            model=spec.id,
            input=messages,
            tools=TOOLS,  # frozen, sorted — part of the cached prefix
            store=False,
        )
        usage.add(response)

        # Check for a refusal BEFORE reading any content. A refusal is a content part inside a
        # message item, not a top-level field, and code that reads content first will crash on it.
        if refusal := _refusal(response):
            raise AgentRefused(refusal)

        if response.status == "incomplete":
            reason = response.incomplete_details.reason if response.incomplete_details else None
            raise AgentTurnLimitExceeded(
                f"the model stopped early on pass {family}: {reason or 'unknown'}"
            )

        # The FULL output, including reasoning items. Dropping them makes the model re-derive its
        # reasoning next turn: worse results, paid for twice.
        messages.extend(response.output)

        for item in response.output:
            if item.type == "reasoning":
                for part in item.summary or []:
                    await emit("reasoning", {"text": part.text})
            elif item.type == "message":
                for part in item.content:
                    if part.type == "output_text" and part.text.strip():
                        await emit("text", {"text": part.text})

        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            # No tools and no finalize: the model has ended its turn on a statement of intent, which
            # the system prompt explicitly forbids. Nudge rather than fail — this is recoverable.
            log.warning("pass %s turn %d: no tool calls", family, turn)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You ended a turn without calling a tool. Continue: address the remaining "
                        "rules in this family, then call finalize."
                    ),
                }
            )
            continue

        for call in calls:
            args = _parse_arguments(call.arguments)
            await emit("tool_call", {"name": call.name, "input": args})

            # A tool that raises still gets a result. Every call_id MUST have a matching output or
            # the next request is rejected — a dropped message wedges the whole analysis.
            try:
                result = await execute_tool(call.name, args)
            except Exception as exc:  # noqa: BLE001 — the model handles this, not the caller
                log.exception("tool %s failed", call.name)
                result = {"error": f"{type(exc).__name__}: {exc}"}

            await emit("tool_result", {"name": call.name, "output": result})

            # ONE message per call. Not batched.
            messages.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result),
                }
            )

            if call.name == "finalize":
                summary = args.get("summary")

        if summary is not None:
            await emit(
                "usage",
                {
                    "input_tokens": usage.input_tokens,
                    "cached_input_tokens": usage.cached_input_tokens,
                    "output_tokens": usage.output_tokens,
                },
            )
            return PassResult(family=family, turns=turn, summary=summary, usage=usage)

    raise AgentTurnLimitExceeded(
        f"pass {family} used all {MAX_TURNS} turns without calling finalize"
    )


def _refusal(response: Response) -> str | None:
    for item in response.output:
        if item.type == "message":
            for part in item.content:
                if part.type == "refusal":
                    return part.refusal
    return None


def _parse_arguments(raw: str) -> dict[str, Any]:
    """Strict mode makes malformed arguments vanishingly unlikely — but 'unlikely' is not 'never',
    and a JSONDecodeError here would kill the analysis rather than the tool call."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
