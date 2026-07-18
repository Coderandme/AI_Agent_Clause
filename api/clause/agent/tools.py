"""The agent's tool surface. SPEC.md §4.4.

Six tools: the five V1 tools, plus `search_document` (V2). The risk scan still reads the whole
document and does not retrieve (SPEC.md §4.1) — search exists so the agent can RE-LOCATE exact
wording it wants to quote, and because Q&A runs on it. Note that `search_document` sorts LAST
alphabetically, which is not luck: appended at the end of the sorted registry, it invalidates the
cached prompt prefix only from its own entry onward, once, on the deploy that adds it (ROADMAP §4).

Three rules govern every schema here, and each of them is load-bearing:

1. `strict: true`, `additionalProperties: false`, and EVERY property listed in `required`. That is
   what strict structured output demands. An optional field is modelled as a nullable union, never
   as an absent key — so `liability_cap: null` means "there is no cap", which is itself one of the
   most valuable things this product can tell a reader.

2. Descriptions are PRESCRIPTIVE about when to call, not merely descriptive of what the tool does.
   "Call this when…" measurably raises the should-call rate. A description that says what a function
   is leaves the model to infer when it is wanted; a description that says when to call it does not.

3. TOOLS is sorted by name and serialised deterministically. Tool definitions sit INSIDE the cached
   prompt prefix (SPEC.md §4.2), so a dict that iterates in a different order on a different process
   would silently invalidate the cache and cost ~10x on input with no error anywhere.

Note what `record_finding` does NOT ask for: page number, character offsets. The agent cannot be
trusted to supply those, so it is not asked to. We derive them in verify.py, from the quote.
"""

from __future__ import annotations

from typing import Any

from clause import rules

_SEVERITY = ["critical", "high", "medium", "low"]
_CONFIDENCE = ["high", "medium", "low"]


def _tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    """Every tool is strict, closed, and fully required. See the module docstring."""
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),  # strict mode requires ALL keys listed
            "additionalProperties": False,
        },
    }


def build_tools() -> list[dict[str, Any]]:
    """Built from the rule library so the rule_id enums can never drift from rules/v1.yaml."""
    rule_ids = list(rules.rule_ids())  # already sorted

    tools = [
        _tool(
            "finalize",
            "Call this when you have addressed every rule in the family you were asked to examine "
            "— that is, when each one has either a recorded finding or a noted absence. This ends "
            "the analysis pass. Do not call it early: a rule you have neither recorded nor noted "
            "is a rule the reader will assume you checked and you did not.",
            {
                "summary": {
                    "type": "string",
                    "description": (
                        "Two or three sentences for a non-lawyer, telling them what this contract "
                        "does to them. Lead with the worst thing. Plain English, no hedging, no "
                        "legal register. This is the first thing the reader sees."
                    ),
                }
            },
        ),
        _tool(
            "get_rule_detail",
            "Call this BEFORE judging whether a rule fires, for every rule you are asked to "
            "examine. Returns the rule's full definition, the exposure it creates, and detection "
            "guidance describing where in a contract this risk tends to hide and what the "
            "near-misses look like. The system prompt gives you only rule names; the guidance is "
            "here, and you will miss findings without it.",
            {
                "rule_id": {
                    "type": "string",
                    "enum": rule_ids,
                    "description": "The rule to load.",
                }
            },
        ),
        _tool(
            "note_absence",
            "Call this when you have checked a rule and it does NOT fire — the contract does not "
            "contain this problem. Every rule in the family needs either this or a finding; none "
            "may be left unaddressed. Telling the reader 'we looked for an uncapped indemnity and "
            "there isn't one' is what makes the review trustworthy rather than merely alarming.",
            {
                "rule_id": {
                    "type": "string",
                    "enum": rule_ids,
                    "description": "The rule that was checked and did not fire.",
                },
                "rationale": {
                    "type": "string",
                    "description": (
                        "One sentence on why it does not fire — what you found instead. "
                        "'The liability cap is mutual and set at 12 months' fees for both "
                        "parties', not 'not applicable'."
                    ),
                },
            },
        ),
        _tool(
            "record_finding",
            "Call this when a rule fires — when the contract contains a term that creates the "
            "exposure the rule describes. Records one risk finding.\n\n"
            "The quotation you supply is VERIFIED against the source document before the finding "
            "is allowed to exist. If it does not appear verbatim, the finding is rejected and the "
            "reader never sees it. You will be told immediately, and you should then quote "
            "correctly or record no finding at all. Do not paraphrase into quoted_text, and do not "
            "reconstruct a clause from memory — a single altered word can reverse what a clause "
            "means.",
            {
                "rule_id": {
                    "type": "string",
                    "enum": rule_ids,
                    "description": "The rule this finding is an instance of.",
                },
                "severity": {
                    "type": "string",
                    "enum": _SEVERITY,
                    "description": (
                        "How much this exposes the READER. About exposure, not about how unusual "
                        "the clause is — a market-standard term that could still bankrupt them is "
                        "critical. May differ from the rule's default when the specific drafting "
                        "warrants it."
                    ),
                },
                "title": {
                    "type": "string",
                    "description": (
                        "Under 80 characters, plain English, specific to THIS contract. 'Renews "
                        "for 24 months unless you cancel 120 days ahead', not 'Auto-renewal "
                        "clause'."
                    ),
                },
                "exposure": {
                    "type": "string",
                    "description": (
                        "What goes wrong, to whom, and what it costs. Two or three sentences a "
                        "founder would feel. Name the interaction if the danger comes from two "
                        "clauses together — 'the cap in section 9 looks protective until section "
                        "14.2 lifts the indemnity out of it'."
                    ),
                },
                "recommendation": {
                    "type": "string",
                    "description": (
                        "The change to ask the counterparty for, in prose the reader could paste "
                        "into an email. Concrete: 'ask for the notice period to drop from 120 days "
                        "to 30', not 'consider negotiating'."
                    ),
                },
                "quoted_text": {
                    "type": "string",
                    "description": (
                        "The clause, copied CHARACTER FOR CHARACTER from the document. 20-600 "
                        "characters. Enough to be evidence on its own. Verified before this "
                        "finding is accepted."
                    ),
                },
                "confidence": {
                    "type": "string",
                    "enum": _CONFIDENCE,
                    "description": (
                        "How clearly the document supports this finding — not how bad the finding "
                        "is. 'low' when the drafting is ambiguous and you are reading it against "
                        "the reader."
                    ),
                },
            },
        ),
        _tool(
            "record_key_terms",
            "Call this ONCE per analysis, in the first pass, before finalizing. Extracts the "
            "commercial spine of the contract into a table the reader sees at a glance.\n\n"
            "Every field is nullable, and a null is MEANINGFUL, not a failure: a null liability "
            "cap means the contract has no cap, which is itself one of the most important things "
            "reader can be told. Use null when the contract is genuinely silent. Do not guess, and "
            "do not fill a field with 'not specified' as a string — use null.",
            {
                "parties": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Legal names of the parties, as written in the contract.",
                },
                "effective_date": {
                    "type": ["string", "null"],
                    "description": "As written in the document, not reformatted.",
                },
                "initial_term": {
                    "type": ["string", "null"],
                    "description": "e.g. '12 months from the Effective Date'.",
                },
                "renewal": {
                    "type": ["string", "null"],
                    "description": (
                        "The renewal mechanics AND the notice window together, since neither means "
                        "anything without the other."
                    ),
                },
                "notice_period": {
                    "type": ["string", "null"],
                    "description": "To terminate or decline renewal. State which, and for whom.",
                },
                "payment_terms": {
                    "type": ["string", "null"],
                    "description": "e.g. 'Net 60, invoiced annually in advance'.",
                },
                "liability_cap": {
                    "type": ["string", "null"],
                    "description": (
                        "The cap, and CRUCIALLY what sits outside it. 'Fees paid in the prior 3 "
                        "months, but indemnities are carved out and uncapped'. null if there is no "
                        "cap at all — which is a critical finding in its own right."
                    ),
                },
                "governing_law": {
                    "type": ["string", "null"],
                    "description": "Governing law, and the forum if it differs.",
                },
                "termination_rights": {
                    "type": ["string", "null"],
                    "description": (
                        "Who may terminate, on what notice, and for what reason. State the "
                        "asymmetry if there is one."
                    ),
                },
            },
        ),
    ]

    tools.append(
        _tool(
            "search_document",
            "Call this ONLY when you need to re-locate the exact wording of a clause you intend "
            "to quote — for instance before record_finding, when you remember the substance of a "
            "term but not its verbatim text. Runs a hybrid (meaning + keyword) search over this "
            "document and returns the most relevant passages verbatim, with section labels and "
            "pages. Do NOT use it to explore the document generally: the full text is already in "
            "your context, and reading it is faster and more complete than searching it.",
            {
                "query": {
                    "type": "string",
                    "description": (
                        "What to look for. Either distinctive words you remember from the clause "
                        "('one hundred and twenty days notice') or a description of its subject "
                        "('limitation of liability carve-outs')."
                    ),
                }
            },
        )
    )

    # Sorted by name. See rule 3 in the module docstring — this is a caching requirement, not
    # tidiness.
    return sorted(tools, key=lambda t: t["name"])


TOOLS: list[dict[str, Any]] = build_tools()

TOOL_NAMES: tuple[str, ...] = tuple(t["name"] for t in TOOLS)
