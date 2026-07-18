"""The chunker's invariants. These guard the citation chain, not cosmetics.

A chunk that is not a verbatim slice of the document breaks char-offset → page resolution — the
same mechanism verified findings use — and it breaks SILENTLY: retrieval still "works", answers
still cite, and the citations point at the wrong place. Hence property tests, not examples.
"""

from __future__ import annotations

from clause.retrieval.chunking import MAX_CHARS, OVERLAP_CHARS, Chunk, chunk_text
from clause.retrieval.embed import vector_literal

# A plausible contract: numbered sections, a schedule, a preamble before any heading — and sections
# LARGE ENOUGH (~2000 chars ≈ 500 tokens each) that the document spans several packs. A fixture
# smaller than one budget collapses into a single chunk and exercises nothing.
CONTRACT = (
    "MASTER SERVICES AGREEMENT\n\nThis Agreement is made between the parties.\n\n"
    "1. Definitions\n" + "In this Agreement, capitalised terms have assigned meanings. " * 30 + "\n"
    "2. Term\n"
    + "The Initial Term runs for twenty-four months from the Effective Date. "
    * 30
    + "\n"
    "9.2 Limitation of Liability\n"
    + "EXCEPT AS PROVIDED IN SECTION 9.3, liability is capped at fees paid. "
    * 30
    + "\n"
    "14.2 Indemnification\n"
    + "Customer shall defend and indemnify Provider against all claims. " * 30
    + "\nSCHEDULE A\nService levels are described in this Schedule.\n"
)


def _slices_are_verbatim(full_text: str, chunks: list[Chunk]) -> None:
    for c in chunks:
        assert c.text == full_text[c.char_start : c.char_end], f"chunk {c.ordinal} is not a slice"


def test_every_chunk_is_a_verbatim_slice() -> None:
    _slices_are_verbatim(CONTRACT, chunk_text(CONTRACT))


def test_every_character_is_covered() -> None:
    """No gaps: a clause that falls between chunks is a clause Q&A can never find."""
    chunks = chunk_text(CONTRACT)
    covered = [False] * len(CONTRACT)
    for c in chunks:
        for i in range(c.char_start, c.char_end):
            covered[i] = True
    assert all(covered), f"gap at char {covered.index(False)}"


def test_section_labels_are_detected_and_carried() -> None:
    labels = {c.section_label for c in chunk_text(CONTRACT)}
    # The packer may merge small neighbours, but the big sections must surface their labels.
    assert "9.2" in labels
    assert "14.2" in labels


def test_oversized_section_is_split_with_overlap() -> None:
    # One giant unheaded blob, > 3 budgets long: must window with overlap, never one huge chunk.
    text = "10.1 Everything\n" + ("word " * 4000)
    chunks = chunk_text(text)
    assert len(chunks) >= 3
    for c in chunks:
        assert (c.char_end - c.char_start) <= MAX_CHARS + 1
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end, "windows of a split section must overlap"
        assert a.char_end - b.char_start >= OVERLAP_CHARS // 2  # about the prescribed overlap
    assert all(c.section_label == "10.1" for c in chunks), "label carried onto every window"
    _slices_are_verbatim(text, chunks)


def test_consecutive_packs_overlap() -> None:
    """A sentence straddling a pack boundary must be whole in at least one chunk."""
    chunks = chunk_text(CONTRACT)
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:], strict=False):
        assert b.char_start < a.char_end


def test_small_document_is_one_chunk() -> None:
    chunks = chunk_text("A short mutual NDA. Nothing to split.")
    assert len(chunks) == 1
    assert chunks[0].char_start == 0


def test_empty_and_whitespace_documents_yield_nothing() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_ordinals_are_dense_and_ordered() -> None:
    chunks = chunk_text(CONTRACT)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_vector_literal_shape() -> None:
    lit = vector_literal([0.125, -1.5, 3.0000001e-05])
    assert lit.startswith("[") and lit.endswith("]")
    assert len(lit.split(",")) == 3
    # pgvector parses plain floats; no whitespace, no scientific surprises that break the cast
    float(lit[1:-1].split(",")[0])
