"""Repairing text extracted from PDFs.

A PDF stores glyph positions, not sentences. Extraction therefore yields text broken at the
line endings of the printed page, with words split across those breaks, page furniture
interleaved with prose, and ligatures encoded as single characters.

None of that matters to a person reading the rendered page, and all of it matters to
retrieval: a chunk containing "signifi- cant improve- ment" does not match a query about
significant improvements, and a passage interrupted by a running header retrieves the header.

These repairs are heuristic. They are ordered so each one runs on input the previous one has
already normalised.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

# Ligatures and typographic punctuation, mapped to their ASCII equivalents so a query typed on
# a normal keyboard matches text lifted from a typeset paper.
_CHARACTER_REPLACEMENTS = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
    "‘": "'",
    "’": "'",
    "‚": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "–": "-",
    "—": "—",
    "−": "-",
    " ": " ",
    " ": " ",
    " ": " ",
    " ": " ",
    "﻿": "",
    "­": "",  # soft hyphen: invisible in print, noise in text
}

_HYPHEN_LINEBREAK = re.compile(r"(\w)[-‐‑]\s*\n\s*(\w)")
# Excludes a newline adjacent to another on either side: that pair is a paragraph break,
# and collapsing half of it would merge two paragraphs into one line.
_SINGLE_NEWLINE = re.compile(r"(?<![.!?:;\n])\n(?![\n])")
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+(?=\n)")
_REPEATED_SPACES = re.compile(r"[ \t]{2,}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# A bare number, or "Page 3", or "3 of 12" — the things printed in a page's margins.
_PAGE_NUMBER_LINE = re.compile(r"^\s*(?:page\s+)?\d{1,4}(?:\s*(?:/|of)\s*\d{1,4})?\s*$", re.I)


def normalise_characters(text: str) -> str:
    """Fold ligatures, quotes, and exotic spaces down to plain characters."""
    text = unicodedata.normalize("NFKC", text)
    for source, replacement in _CHARACTER_REPLACEMENTS.items():
        text = text.replace(source, replacement)
    return _CONTROL_CHARACTERS.sub("", text)


def rejoin_hyphenated_words(text: str) -> str:
    """Re-form words the typesetter split across a line break.

    Only applies at a line break: a hyphen that survives on one line is real ("state-of-the-art")
    and must be left alone.
    """
    return _HYPHEN_LINEBREAK.sub(r"\1\2", text)


def unwrap_lines(text: str) -> str:
    """Turn hard-wrapped lines back into flowing prose.

    A newline that does not follow sentence-ending punctuation is line wrapping, not a
    paragraph break. Blank lines are preserved — they are the real paragraph boundaries.

    Applied when building chunk content, **not** when cleaning a page. Headings, title
    blocks, and author lists are identified by their line structure, so unwrapping before
    those run would glue a heading to the paragraph beneath it.
    """
    return _SINGLE_NEWLINE.sub(" ", text)


def strip_page_furniture(pages: Sequence[str], *, threshold: float = 0.6) -> list[str]:
    """Remove running headers, footers, and page numbers.

    Detected by repetition rather than position: a line appearing at the top or bottom of most
    pages is furniture, whatever it says. The threshold is high enough that a short section
    heading repeated on two pages of a long paper survives.

    Skipped for very short documents, where "appears on most pages" is not evidence of
    anything.
    """
    if len(pages) < 4:
        return [_drop_page_numbers(page) for page in pages]

    edge_lines: Counter[str] = Counter()
    for page in pages:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        # Only the first and last two lines of a page can be furniture.
        for line in {*lines[:2], *lines[-2:]}:
            if 0 < len(line) <= 120:
                edge_lines[line] += 1

    minimum = max(3, int(len(pages) * threshold))
    furniture = {line for line, count in edge_lines.items() if count >= minimum}

    cleaned: list[str] = []
    for page in pages:
        kept = [line for line in page.splitlines() if line.strip() not in furniture]
        cleaned.append(_drop_page_numbers("\n".join(kept)))
    return cleaned


def _drop_page_numbers(page: str) -> str:
    return "\n".join(line for line in page.splitlines() if not _PAGE_NUMBER_LINE.match(line))


def tidy_whitespace(text: str) -> str:
    text = _TRAILING_SPACES.sub("", text)
    text = _REPEATED_SPACES.sub(" ", text)
    text = _EXCESS_BLANK_LINES.sub("\n\n", text)
    return text.strip()


def clean_page(text: str) -> str:
    """Repair one page while preserving its line structure.

    Deliberately does not unwrap lines. Section headings, the title block, and the author
    list are all recognised by where the line breaks fall, so that step belongs later — see
    `unwrap_lines`.
    """
    text = normalise_characters(text)
    text = rejoin_hyphenated_words(text)
    return tidy_whitespace(text)


def estimate_tokens(text: str) -> int:
    """Approximate token count without loading a tokeniser.

    Used for chunk sizing and context budgeting, where being within ~10% is sufficient and a
    per-provider tokeniser dependency is not worth its weight. Four characters per token is
    the standard approximation for English prose; technical text with many symbols runs
    slightly denser, so this errs toward over-counting, which is the safe direction for a
    budget.
    """
    return max(1, len(text) // 4)
