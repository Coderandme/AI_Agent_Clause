"""Text normalisation for matching quotes against extracted PDF text.

This exists because of a gap that is invisible until you hit it: the agent quotes a clause as clean
prose, but the document it came from contains that clause hard-wrapped across lines, with
typographic quotes and en-dashes the model silently straightens. A raw substring match fails on
text that is unambiguously present.

    document:  "...are not subject to the\nlimitations of liability set out in\nSection 9."
    agent:     "...are not subject to the limitations of liability set out in Section 9."

Both are the same clause. Only one of them is findable with `str.find`.

So normalisation is step one of quote verification (SPEC.md §4.5), and it must be applied to BOTH
sides — the document and the quote — using exactly this function, or offsets computed against one
will not mean anything against the other.
"""

from __future__ import annotations

import re

_WHITESPACE = re.compile(r"\s+")

# Glyphs a model routinely substitutes when it reproduces a quote. Mapping them to ASCII costs us
# nothing (they are the same character to a reader) and removes a whole class of spurious mismatch.
_GLYPHS = str.maketrans(
    {
        "‘": "'",  # left single quote
        "’": "'",  # right single quote / apostrophe
        "‚": "'",
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "„": '"',
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus sign
        " ": " ",  # non-breaking space
        "…": "...",  # ellipsis
        "ﬁ": "fi",  # ligatures, which PDF extraction produces and models do not
        "ﬂ": "fl",
    }
)


def normalize(text: str) -> str:
    """Collapse whitespace, unify glyphs, casefold. Applied to both document and quote."""
    return _WHITESPACE.sub(" ", text.translate(_GLYPHS)).strip().casefold()


def normalized_offsets(text: str) -> list[int]:
    """Map each character of `normalize(text)` back to its offset in the ORIGINAL text.

    This is the piece that makes normalisation safe rather than lossy. Verification finds a quote in
    the normalised document, but `findings.char_start` must point into the ORIGINAL text — because
    that is what `pages` is indexed against, and what the highlight overlay walks. Without this map,
    normalising would destroy the very offsets we normalise in order to find.

    Returns a list the same length as `normalize(text)`, where result[i] is the index in `text` of
    the character that produced normalised character i.
    """
    offsets: list[int] = []
    out: list[str] = []
    pending_space = False
    started = False

    for i, ch in enumerate(text):
        mapped = ch.translate(_GLYPHS)

        if mapped.isspace():
            if started:
                pending_space = True
            continue

        if pending_space:
            out.append(" ")
            offsets.append(i)  # the space is attributed to the character that follows it
            pending_space = False

        for c in mapped.casefold():
            out.append(c)
            offsets.append(i)
        started = True

    assert len(offsets) == len("".join(out))
    return offsets
