"""The hallucination guard. SPEC.md §8.2 names this as one of two invariants with its own test,
"because both fail silently in production".

The single most important assertion in this repository is `test_a_fabricated_quote_never_verifies`.
Every claim the product makes rests on it: if a quote the model invented can reach verified=True,
then "every quotation you see provably exists in your document" is a lie, and the landing page is
making a promise the system does not keep.

The tests are deliberately adversarial. Plausible fabrications — right vocabulary, right register,
right section numbers, wrong document — are the realistic failure, not obvious nonsense.
"""

from __future__ import annotations

import pytest

from clause.agent.verify import DocumentIndex, verify
from clause.config import REPO_ROOT
from clause.ingest import parse

MSA = REPO_ROOT / "demo" / "contracts" / "saas_msa.pdf"


@pytest.fixture(scope="module")
def index() -> DocumentIndex:
    if not MSA.exists():
        pytest.skip("run `python demo/build_pdfs.py` first")
    doc = parse.parse(MSA.read_bytes())
    return DocumentIndex(
        full_text=doc.full_text,
        pages=[(p.page_number, p.char_start, p.char_end) for p in doc.pages],
    )


# ── The quotes really are in the document ────────────────────────────────────────────────────────


def test_a_real_quote_verifies_and_lands_on_the_right_page(index: DocumentIndex) -> None:
    """The cross-clause trap: §14.2 lifts the indemnity out of the §9 cap."""
    result = verify(
        "The indemnification obligations set out in Section 14.1 are not subject to the "
        "limitations of liability set out in Section 9.",
        index,
    )
    assert result.verified
    assert result.page_number == 4
    assert result.char_start is not None and result.char_end is not None
    # The span must point at the actual clause, not merely somewhere in the document.
    assert "not subject to the limitations" in index.full_text[result.char_start : result.char_end]


def test_a_quote_the_pdf_hard_wrapped_still_verifies(index: DocumentIndex) -> None:
    """The agent quotes clean prose; the PDF contains it wrapped across lines. Normalisation is
    what closes that gap, and without it every honest finding would be rejected."""
    result = verify(
        "must be received by Provider not less than one hundred and twenty (120) days prior to "
        "the end of the then-current Term",
        index,
    )
    assert result.verified
    assert result.page_number == 5


def test_typographic_substitution_still_verifies(index: DocumentIndex) -> None:
    """Models silently straighten curly quotes and en-dashes. That is not a misquote."""
    result = verify(
        "Customer’s continued use of the Services following the posting of a revised Acceptable "
        "Use Policy constitutes acceptance of it.",
        index,
    )
    assert result.verified


# ── The quotes do NOT exist, and must not be allowed to ──────────────────────────────────────────


def test_a_fabricated_quote_never_verifies(index: DocumentIndex) -> None:
    """THE test. A clause that sounds exactly like this contract but is not in it.

    Note what makes this adversarial: it uses the contract's own vocabulary ("Provider",
    "Customer", "Agreement"), its register, and a real section number. It is the kind of thing a
    model produces when it is confidently reconstructing from memory rather than reading — which is
    precisely the failure this guard exists to catch.
    """
    result = verify(
        "Provider shall indemnify and hold harmless Customer against any and all claims arising "
        "from Provider's gross negligence or wilful misconduct under this Agreement.",
        index,
    )
    assert not result.verified
    assert result.char_start is None
    assert result.page_number is None
    assert result.reason is not None


def test_a_corrupted_quote_never_verifies(index: DocumentIndex) -> None:
    """SPEC.md §8.2: "tested with a deliberately corrupted quote".

    A real clause with its meaning inverted. This is the nastiest case, because it shares most of
    its characters with genuine text — exactly the case a fuzzy threshold set too low would wave
    through, and it would invert the finding's meaning while pointing at a real span.
    """
    result = verify(
        "The indemnification obligations set out in Section 14.1 are fully subject to the "
        "limitations of liability set out in Section 9 and may not exceed the fees paid.",
        index,
    )
    assert not result.verified


def test_a_quote_from_a_different_contract_never_verifies(index: DocumentIndex) -> None:
    result = verify(
        "Tenant shall maintain commercial general liability insurance with limits of not less "
        "than Two Million Dollars ($2,000,000) per occurrence throughout the Lease Term.",
        index,
    )
    assert not result.verified


def test_an_empty_or_tiny_quote_never_verifies(index: DocumentIndex) -> None:
    """Short strings fuzzy-match almost anything, which is the whole reason for a floor."""
    for junk in ["", "   ", "Section 9", "the Agreement", "Provider"]:
        assert not verify(junk, index).verified


def test_the_failure_reason_tells_the_agent_what_to_do(index: DocumentIndex) -> None:
    """The tool result is fed back to the model, so the reason is a PROMPT, not a log line. It has
    to tell the agent how to recover, or the retry is just another guess."""
    result = verify(
        "Provider warrants that the Services shall be free from all defects in perpetuity.", index
    )
    assert not result.verified
    assert "do not paraphrase" in (result.reason or "").lower()


# ── Single-word substitutions: the case a similarity score cannot catch ──────────────────────────
#
# These are the regression tests for a real bug. Implemented as SPEC.md §4.5 literally describes it
# — "rapidfuzz partial_ratio >= 95 -> verified" — the guard PASSED the first quote below with a
# score of 96.1, because flipping one word in a 123-character clause costs only four points of
# character similarity while reversing the clause's meaning entirely.
#
# A quote that inverts the document, anchored to a real page with a real highlight, is worse than no
# finding at all. If these tests fail, the product's central claim is false.


def test_a_flipped_negation_never_verifies(index: DocumentIndex) -> None:
    """The document says "are not subject to". This says "are fully subject to".

    Scores 96.1 on partial_ratio. Must not verify.
    """
    result = verify(
        "The indemnification obligations set out in Section 14.1 are fully subject to the "
        "limitations of liability set out in Section 9.",
        index,
    )
    assert not result.verified, (
        "a one-word negation flip verified — the guard is authorising on character similarity, "
        "and the agent can now quote the contract as saying the opposite of what it says"
    )


def test_a_reversed_party_never_verifies(index: DocumentIndex) -> None:
    """The document gives PROVIDER termination for convenience. This claims CUSTOMER has it —
    reversing which party the clause protects, which is the entire substance of the finding."""
    result = verify(
        "Customer may terminate this Agreement at any time, for any reason or no reason, upon "
        "thirty (30) days' written notice to Provider.",
        index,
    )
    assert not result.verified


def test_a_swapped_number_never_verifies(index: DocumentIndex) -> None:
    """The notice window is 120 days — that is what makes the auto-renewal a trap. At 30 days it
    would be unremarkable. One token, and the finding's severity changes completely."""
    result = verify(
        "Any notice of non-renewal under Section 3.2 must be received by Provider not less than "
        "thirty (30) days prior to the end of the then-current Term.",
        index,
    )
    assert not result.verified


def test_an_appended_clause_never_verifies(index: DocumentIndex) -> None:
    """A real clause with a fabricated tail bolted on. The prefix is genuine, so a locate-only
    guard would happily anchor it — and the user would read a promise the contract never made."""
    result = verify(
        "Provider may terminate this Agreement at any time, for any reason or no reason, upon "
        "thirty (30) days' written notice to Customer, and shall refund all prepaid fees on a "
        "pro-rata basis.",
        index,
    )
    assert not result.verified


def test_source_side_damage_is_still_forgiven(index: DocumentIndex) -> None:
    """The other side of the asymmetry, and the reason the guard is not simply an exact match.

    The SOURCE may carry junk — a hyphen split by line wrapping, a page-break header. Those leave
    the quote's words intact and in order, and must still verify, or every honest finding on a real
    PDF gets rejected and unverified_count goes through the roof.
    """
    result = verify(
        "Customer shall pay each invoice within sixty (60) days of the invoice date.", index
    )
    assert result.verified
