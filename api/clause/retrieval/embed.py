"""Turn text into vectors, via OpenAI's embedding API. SPEC.md §3.3, as amended — see models.py for
why this is an API call and not the local ONNX model the spec first chose (short version: Render's
512 MB won't hold an ONNX runtime, and the API costs ~$0.0006 per contract).

The `dimensions` parameter asks the model for 384-dim vectors directly, which is what lets the
vector(384) column and HNSW index from migration 001 survive the provider switch untouched.
"""

from __future__ import annotations

from openai import AsyncOpenAI

from clause import models

# The API accepts up to 2048 inputs per request, but a conservative batch keeps any single request's
# token total well under the per-request ceiling. A 30-page contract is ~60 chunks — one batch.
_BATCH = 128


async def embed_texts(client: AsyncOpenAI, texts: list[str]) -> tuple[list[list[float]], int]:
    """Embed texts in order. Returns (vectors, total_tokens_billed)."""
    vectors: list[list[float]] = []
    tokens = 0
    for i in range(0, len(texts), _BATCH):
        batch = texts[i : i + _BATCH]
        resp = await client.embeddings.create(
            model=models.EMBEDDING_MODEL,
            input=batch,
            dimensions=models.EMBEDDING_DIM,
        )
        # The API documents that results carry an index; sort rather than assume response order.
        for item in sorted(resp.data, key=lambda d: d.index):
            vectors.append(item.embedding)
        tokens += resp.usage.total_tokens if resp.usage else 0
    return vectors, tokens


def vector_literal(vector: list[float]) -> str:
    """A pgvector text literal, e.g. '[0.12,-0.3,...]', for `$n::vector` casts.

    asyncpg has no built-in codec for the vector type; the text form is the simple, correct way in
    and it round-trips exactly at this precision. %.7g keeps ~float32 significance, which is all the
    model emits anyway, at roughly half the bytes of full repr.
    """
    return "[" + ",".join(f"{x:.7g}" for x in vector) + "]"
