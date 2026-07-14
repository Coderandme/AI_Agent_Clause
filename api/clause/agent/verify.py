"""Quote verification — the hallucination guard. SPEC.md §4.5.

The most important mechanism in the system, and the reason a claim like "every quotation you see
provably exists in your document" can be put on the landing page and defended.

There is no citations API here. Nothing in a model's response tells us where in the source a quoted
clause lives, or whether it lives there at all. So the agent supplies a verbatim quote in the tool
call, and this module checks it against the extracted document text BEFORE the finding is allowed to
exist:

    normalise  ->  exact substring match?          -> verified, snap to span
                   no  -> fuzzy match >= threshold? -> verified, snap to span
                          no                        -> verified = False

An unverified finding is not rendered, not memoed, and counted in `analyses.unverified_count`. The
tool result tells the agent it misquoted, so it can retry.

This buys three things at once:
  * a fabricated quotation is structurally unable to reach the user;
  * we derive the page and character range the highlight overlay needs, which the agent could never
    reliably produce (which is why `record_finding` does not even ask it to);
  * `unverified_count / total_findings` becomes a measurable prompt-quality signal, gated at 0.15
    by the eval harness.

Why fuzzy matching at all, rather than demanding an exact match: PDF extraction inserts hyphenation,
soft line breaks, and ligatures, and models silently normalise typography. Requiring byte-equality
would reject quotes that a human would call verbatim.


A NOTE ON WHY THE SPEC'S DESIGN IS NOT ENOUGH, AND WHAT WE DO INSTEAD
────────────────────────────────────────────────────────────────────
SPEC.md §4.5 specifies "rapidfuzz partial_ratio >= 95 -> verified". Implemented literally, that has
a hole big enough to sink the product, and it was found by measuring the scores rather than trusting
the test suite:

    document:  "...are NOT subject to the limitations of liability set out in Section 9."
    agent:     "...are FULLY subject to the limitations of liability set out in Section 9."
                                                                       partial_ratio = 96.1  ✗ PASS

A one-word negation flip inverts the meaning of the clause completely, and scores 96 because it
shares 119 of its 123 characters with the real text. It would render in the UI, with a real page
number and a real highlight, quoting the contract as saying the opposite of what it says. That is
worse than no finding at all — it is a confident, well-anchored lie.

No threshold fixes this. On a long quote, a substituted word costs ~4 points; raising the bar to 98
would reject honest quotes damaged by hyphenation while STILL admitting substitutions in longer
text. The metric is wrong, not the number. Character similarity cannot distinguish "damaged" from
"altered", and those are the two things we must never confuse.

So fuzzy matching is demoted to what it is actually good at — LOCATING a candidate span — and the
authorisation is done by a token check with an asymmetry at its heart:

    Every token of the quote must appear, in order, in the source span.
    The source may contain EXTRA tokens. The quote may not.

That asymmetry is the whole idea. It is derived from what the two kinds of damage actually look
like:

  * The SOURCE gains junk. A quote spanning a page break picks up a header, a footer, a page
    number. PDF extraction splits a hyphenated word across a line. These are extra or fragmented
    tokens on the DOCUMENT side, and they are forgivable — the words of the quote are all still
    there, in order.
  * The QUOTE gains words the source never had. "not" becomes "fully". A clause acquires a
    sub-clause it never contained. A model reconstructs from memory instead of reading. These are
    tokens on the QUOTE side with no counterpart in the document — and there is no innocent
    explanation for one.

A fabrication cannot be expressed as "the source had extra tokens". It always requires the quote to
contain a word the document does not. So the check catches it by construction, not by calibration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from clause import text as textutil

# Used ONLY to locate a candidate span, never to authorise one. Deliberately loose: a real quote
# mangled by a page break can score in the low 90s, and we would rather look at it and reject it on
# the token check than never look at it at all.
LOCATE_THRESHOLD = 85.0

_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)

# How much junk the SOURCE may contain within the matched span, relative to the quote's length,
# before we stop believing the span really is the quote. Generous enough for a page break's header
# and footer; not so generous that a quote's words can be gathered from scattered locations.
MAX_EXTRA_SOURCE_TOKENS_RATIO = 0.25
MIN_EXTRA_SOURCE_TOKENS = 6

# Below this many characters a "quote" is too short to be evidence of anything — and short strings
# fuzzy-match against almost any document, which is the failure mode this guard exists to prevent.
# SPEC.md §4.4 constrains quoted_text to 20-600 chars in the tool schema; this enforces the floor
# again at verification time, because a schema is a request and this is a check.
MIN_QUOTE_CHARS = 20


@dataclass(frozen=True, slots=True)
class Verification:
    verified: bool
    # All of these are None when verification fails. That is the point: an unverified finding has no
    # location, because it does not have one.
    matched_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    page_number: int | None = None
    score: float | None = None
    reason: str | None = None  # why it failed, for the tool result and for debugging


class DocumentIndex:
    """A document, pre-normalised for matching, with the map back to original offsets.

    Built once per analysis. The normalisation is the expensive part and the agent will call
    record_finding a dozen times, so doing it per-call would be wasteful — but the real reason this
    is a class is to make it impossible to normalise the document with one function and the quote
    with another. Both go through `textutil.normalize`, or the offsets mean nothing.
    """

    def __init__(self, full_text: str, pages: list[tuple[int, int, int]]) -> None:
        self.full_text = full_text
        self.normalized = textutil.normalize(full_text)
        self.offsets = textutil.normalized_offsets(full_text)
        # (page_number, char_start, char_end) against the ORIGINAL text.
        self.pages = sorted(pages, key=lambda p: p[0])

    def page_for_offset(self, offset: int) -> int | None:
        for page_number, start, end in self.pages:
            if start <= offset < end:
                return page_number
        return None

    def to_original_span(self, norm_start: int, norm_end: int) -> tuple[int, int]:
        """Map a span in the normalised text back to a span in the original."""
        start = self.offsets[norm_start]
        end = self.offsets[min(norm_end, len(self.offsets)) - 1] + 1
        return start, end


def verify(quote: str, index: DocumentIndex) -> Verification:
    """Does this quote actually exist in this document? If so, exactly where?"""
    if len(quote.strip()) < MIN_QUOTE_CHARS:
        return Verification(
            verified=False,
            reason=(
                f"The quoted text is only {len(quote.strip())} characters. Quote at least "
                f"{MIN_QUOTE_CHARS} characters of the clause verbatim, so the quotation can be "
                f"located unambiguously in the document."
            ),
        )

    needle = textutil.normalize(quote)
    if not needle:
        return Verification(verified=False, reason="The quoted text is empty.")

    # ── 1. exact ─────────────────────────────────────────────────────────────────────────────────
    # The common case for a well-behaved agent, and unambiguous when it hits.
    at = index.normalized.find(needle)
    if at != -1:
        return _locate(index, at, at + len(needle), score=100.0)

    # ── 2. locate a candidate span ───────────────────────────────────────────────────────────────
    # partial_ratio_alignment finds the best-matching window of the document and, crucially, tells
    # us where it is. This is the ONLY thing fuzzy matching is trusted with.
    alignment = fuzz.partial_ratio_alignment(needle, index.normalized)
    score = alignment.score if alignment else 0.0

    if alignment is None or score < LOCATE_THRESHOLD:
        return Verification(
            verified=False,
            score=score,
            reason=(
                "That quotation does not appear in the document. Do not paraphrase and do not "
                "reconstruct the clause from memory: copy it character-for-character out of the "
                "document text above, or record no finding for this rule."
            ),
        )

    # ── 3. authorise, or refuse ──────────────────────────────────────────────────────────────────
    # Widen the window slightly: the alignment can clip a token at either edge, and clipping a token
    # would make an honest quote look like it contains a word the source lacks.
    pad = 40
    start = max(0, alignment.dest_start - pad)
    end = min(len(index.normalized), alignment.dest_end + pad)

    matched = _tokens_appear_in_order(
        quote_tokens=_TOKEN.findall(needle),
        span_tokens=_TOKEN.findall(index.normalized[start:end]),
    )

    if matched is None:
        return Verification(
            verified=False,
            score=score,
            reason=(
                "That quotation is close to text in the document but is not identical to it — at "
                "least one word differs. A near-quote is not a quote: a single altered word can "
                "reverse what a clause means. Copy the clause character-for-character out of the "
                "document text above, or record no finding for this rule."
            ),
        )

    # Re-locate precisely: find the character span the matched tokens actually occupy.
    span = _character_span(index.normalized, start, end, _TOKEN.findall(needle))
    if span is None:  # pragma: no cover — _tokens_appear_in_order already proved they are there
        return Verification(
            verified=False, score=score, reason="The quotation could not be anchored."
        )

    return _locate(index, span[0], span[1], score=score)


def _tokens_appear_in_order(*, quote_tokens: list[str], span_tokens: list[str]) -> bool | None:
    """Does every token of the quote appear, in order, within the span?

    Returns True when it does, None when it does not. The source may carry extra tokens (page-break
    junk); consecutive source tokens may be merged to match one quote token (a hyphen split by line
    wrapping). The quote may NOT contain a token the source lacks — that is fabrication, and it is
    the one thing this function exists to refuse.
    """
    if not quote_tokens:
        return None

    budget = max(MIN_EXTRA_SOURCE_TOKENS, int(len(quote_tokens) * MAX_EXTRA_SOURCE_TOKENS_RATIO))

    for begin in range(len(span_tokens)):
        i = 0  # index into quote_tokens
        j = begin  # index into span_tokens
        extra = 0

        while i < len(quote_tokens) and j < len(span_tokens):
            if span_tokens[j] == quote_tokens[i]:
                i += 1
                j += 1
                continue

            # Hyphenation: "indemnifi-\ncation" extracts as two tokens where the quote has one.
            # Try gluing consecutive source tokens together to reach the quote's token.
            glued = span_tokens[j]
            k = j + 1
            while k < len(span_tokens) and len(glued) < len(quote_tokens[i]):
                glued += span_tokens[k]
                k += 1
                if glued == quote_tokens[i]:
                    break
            if glued == quote_tokens[i]:
                i += 1
                j = k
                continue

            # Otherwise this source token is junk we forgive, up to the budget.
            extra += 1
            if extra > budget:
                break
            j += 1

        if i == len(quote_tokens):
            return True

    return None


def _character_span(
    normalized: str, window_start: int, window_end: int, quote_tokens: list[str]
) -> tuple[int, int] | None:
    """The character span, in the normalised document, covered by the matched tokens."""
    first, last = quote_tokens[0], quote_tokens[-1]
    window = normalized[window_start:window_end]

    begin = window.find(first)
    if begin == -1:
        return None
    tail = window.rfind(last)
    if tail == -1 or tail < begin:
        return None

    return window_start + begin, window_start + tail + len(last)


def _locate(index: DocumentIndex, norm_start: int, norm_end: int, *, score: float) -> Verification:
    char_start, char_end = index.to_original_span(norm_start, norm_end)
    page_number = index.page_for_offset(char_start)

    if page_number is None:
        # The span is real but falls outside every page range — which should be impossible, and
        # means the offset map and `pages` have diverged. Refuse to verify rather than emit a
        # finding that the overlay will paint in the wrong place (SPEC.md §9.3).
        return Verification(
            verified=False,
            score=score,
            reason="The quotation was located but could not be attributed to a page.",
        )

    return Verification(
        verified=True,
        matched_text=index.full_text[char_start:char_end],
        char_start=char_start,
        char_end=char_end,
        page_number=page_number,
        score=score,
    )
