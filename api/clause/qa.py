"""Grounded Q&A over one document. SPEC.md §2.3 (the Ask tab), §3.4 (retrieval), §3.2 (tiering).

THE SHAPE: retrieve first, then answer — not an agent loop. The question is embedded, hybrid search
pulls the ~8 most relevant chunks, and `gpt-5.4-mini` answers FROM THOSE EXCERPTS ONLY, streaming
tokens as it goes. One model call, ~$0.007 a question. (A multi-hop agentic Q&A that re-searches
mid-answer is a plausible refinement; it is not needed to answer "what's the notice period?".)

WHY THE CITATIONS CAN BE TRUSTED. The excerpts are sent to the browser BEFORE the model says a
word, and each one is a chunk — which the chunker guarantees is a verbatim slice of the document
with real char offsets (retrieval/chunking.py). The model can only cite [1]-[k] from that list. So
a citation always points at text that provably exists at a known page; the model cannot invent a
source, only pick among real ones. Whether the model's *sentence* fairly summarises its source is
for the reader to check — which is exactly one click, because the citation carries the page.

COST DISCIPLINE: mini, not sol — SPEC §3.2's tiering. Q&A is many narrow questions; the flagship
would cost 30x for no visible gain. Every answer's cost lands in the usage ledger, under the same
monthly ceiling as everything else.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

from openai import AsyncOpenAI

from clause import guard, models
from clause.config import settings
from clause.db import pool
from clause.retrieval.search import SearchHit, search

log = logging.getLogger(__name__)

TOP_K = 8

QA_SYSTEM = """\
You answer questions about ONE commercial contract, for a non-lawyer who is a party to it.

You are given numbered excerpts from the contract. They are verbatim. Rules:

1. Answer ONLY from the excerpts. If they do not contain the answer, say exactly that — "the \
excerpts retrieved for this question don't cover it" — and suggest what to look for instead. \
Never fill gaps from general knowledge of how contracts usually work.
2. Cite every factual claim with the excerpt number in square brackets, like [2]. Cite the \
specific excerpt the words came from, not a list of everything vaguely related.
3. Plain English. Short. Lead with the answer, then the caveat if there is one.
4. Quote the contract's own words for anything load-bearing (amounts, deadlines, notice periods).
5. You are not a lawyer and this is not legal advice; do not say otherwise.\
"""


def _excerpt_block(hits: list[SearchHit], pages: dict[int, int | None]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        where = f"§{h.section_label}" if h.section_label else "unlabelled section"
        page = pages.get(h.ordinal)
        page_s = f", page {page}" if page else ""
        parts.append(f"[{i}] ({where}{page_s})\n{h.text}")
    return "\n\n---\n\n".join(parts)


async def ask_stream(
    document_id: UUID, question: str, spend_key: str
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    """Yields SSE-ready (event, payload) pairs: `citations` once, `delta` many, then `done`.

    Connection discipline: a pooled connection is held for the search and released BEFORE the model
    streams (10-15s), then re-acquired for the ledger write — a Neon connection idling under an LLM
    stream is exactly what ROADMAP §5.1 says not to do.
    """
    spec = models.for_task(models.Task.QA)
    client = AsyncOpenAI(api_key=settings().openai_api_key)

    p = await pool.pool()
    async with p.acquire() as conn:
        hits = await search(conn, client, document_id, question, limit=TOP_K)
        page_rows = await conn.fetch(
            "SELECT page_number, char_start, char_end FROM pages WHERE document_id = $1",
            document_id,
        )

    if not hits:
        yield (
            "error",
            {
                "message": "This document isn't indexed for Q&A. Documents uploaded before Q&A "
                "existed weren't indexed — and every upload is deleted after 24 hours, so the fix "
                "is simply to upload it again."
            },
        )
        return

    def page_for(offset: int) -> int | None:
        for r in page_rows:
            if r["char_start"] <= offset < r["char_end"]:
                return int(r["page_number"])
        return None

    hit_pages = {h.ordinal: page_for(h.char_start) for h in hits}

    # The citation map goes out before the first token, so every [n] the model emits is clickable
    # the moment it appears.
    yield (
        "citations",
        {
            "citations": [
                {
                    "n": i,
                    "section_label": h.section_label,
                    "page": hit_pages.get(h.ordinal),
                    "char_start": h.char_start,
                    "char_end": h.char_end,
                    "preview": " ".join(h.text[:220].split()),
                }
                for i, h in enumerate(hits, 1)
            ]
        },
    )

    messages: list[Any] = [
        {"role": "system", "content": QA_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Excerpts from the contract:\n\n{_excerpt_block(hits, hit_pages)}\n\n"
                f"Question: {question}"
            ),
        },
    ]

    input_tokens = cached = output_tokens = 0
    stream = await client.responses.create(model=spec.id, input=messages, stream=True, store=False)
    async for event in stream:
        if event.type == "response.output_text.delta":
            yield ("delta", {"text": event.delta})
        elif event.type == "response.completed":
            u = event.response.usage
            if u is not None:
                input_tokens, output_tokens = u.input_tokens, u.output_tokens
                if u.input_tokens_details is not None:
                    cached = u.input_tokens_details.cached_tokens

    cost = spec.cost_microdollars(
        input_tokens=input_tokens, cached_input_tokens=cached, output_tokens=output_tokens
    )
    async with p.acquire() as conn:
        await guard.record_spend(conn, ip=spend_key, cost_microdollars=cost)

    yield (
        "done",
        {"cost_microdollars": cost, "input_tokens": input_tokens, "output_tokens": output_tokens},
    )
