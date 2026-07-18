"""Index a document's chunks, and search them. SPEC.md §3.4 — the hybrid query, verbatim.

WHY HYBRID AND NOT JUST VECTORS. Semantic search finds "what happens if we stop paying?" →
termination-for-nonpayment clauses that share no words with the question. Lexical (keyword) search
finds "Section 9.3" and defined terms like "Renewal Term" *exactly*, which embeddings smear. Legal
Q&A needs both constantly, so every query runs both and blends the scores 0.7 semantic / 0.3
lexical — the spec's starting weights, to be tuned against the eval set (V3), not guessed further.

Retrieval exists FOR Q&A. The risk scan reads the whole document and never touches this module
(SPEC.md §4.1) — a cap in §9 gutted by a carve-out in §14 is exactly what retrieval would miss.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

import asyncpg
from openai import AsyncOpenAI

from clause.retrieval.chunking import chunk_text
from clause.retrieval.embed import embed_texts, vector_literal

log = logging.getLogger(__name__)

SEMANTIC_WEIGHT = 0.7
LEXICAL_WEIGHT = 0.3


async def index_document(
    conn: asyncpg.Connection,
    client: AsyncOpenAI,
    document_id: UUID,
    full_text: str | None = None,
) -> int:
    """Chunk + embed one document into `chunks`. Idempotent: re-indexing replaces. Returns count.

    Runs inside the upload's background job (analysis/service.py), where its ~1-2s cost is invisible
    next to the 60-80s scan. A failure here is logged and non-fatal — Q&A degrades to "not indexed",
    the risk scan (the marquee) is unaffected.
    """
    if full_text is None:
        full_text = await conn.fetchval(
            "SELECT full_text FROM documents WHERE id = $1", document_id
        )
    if not full_text or not full_text.strip():
        return 0

    chunks = chunk_text(full_text)
    if not chunks:
        return 0

    vectors, tokens = await embed_texts(client, [c.text for c in chunks])

    async with conn.transaction():
        # Replace, not append: re-running an analysis must not double-index the document.
        await conn.execute("DELETE FROM chunks WHERE document_id = $1", document_id)
        await conn.executemany(
            """
            INSERT INTO chunks (id, document_id, ordinal, section_label, char_start, char_end,
                                text, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector)
            """,
            [
                (
                    uuid4(),
                    document_id,
                    c.ordinal,
                    c.section_label,
                    c.char_start,
                    c.char_end,
                    c.text,
                    vector_literal(v),
                )
                for c, v in zip(chunks, vectors, strict=True)
            ],
        )

    log.info("indexed %s: %d chunks, %d embedding tokens", document_id, len(chunks), tokens)
    return len(chunks)


@dataclass(slots=True)
class SearchHit:
    ordinal: int
    section_label: str | None
    char_start: int
    char_end: int
    text: str
    score: float


async def search(
    conn: asyncpg.Connection,
    client: AsyncOpenAI,
    document_id: UUID,
    query: str,
    *,
    limit: int = 8,
) -> list[SearchHit]:
    """The spec's hybrid query (§3.4): top-20 semantic ∪ top-20 lexical, blended 0.7/0.3, top-k."""
    qvec, _ = await embed_texts(client, [query])

    rows = await conn.fetch(
        f"""
        WITH semantic AS (
          SELECT id, 1 - (embedding <=> $1::vector) AS score
          FROM chunks WHERE document_id = $2
          ORDER BY embedding <=> $1::vector LIMIT 20
        ),
        lexical AS (
          SELECT id, ts_rank_cd(tsv, plainto_tsquery('english', $3)) AS score
          FROM chunks WHERE document_id = $2 AND tsv @@ plainto_tsquery('english', $3)
          ORDER BY score DESC LIMIT 20
        )
        SELECT c.ordinal, c.section_label, c.char_start, c.char_end, c.text,
               COALESCE(s.score, 0) * {SEMANTIC_WEIGHT} + COALESCE(l.score, 0) * {LEXICAL_WEIGHT}
                 AS score
        FROM chunks c
        LEFT JOIN semantic s ON s.id = c.id
        LEFT JOIN lexical  l ON l.id = c.id
        WHERE s.id IS NOT NULL OR l.id IS NOT NULL
        ORDER BY score DESC LIMIT $4
        """,
        vector_literal(qvec[0]),
        document_id,
        query,
        limit,
    )
    return [
        SearchHit(
            ordinal=r["ordinal"],
            section_label=r["section_label"],
            char_start=r["char_start"],
            char_end=r["char_end"],
            text=r["text"],
            score=float(r["score"]),
        )
        for r in rows
    ]
