"""Splitting a bibliography into individual references.

A references section arrives as one run of text with the entries wrapped across lines. Getting
them apart is worth the effort for two reasons: a reader following an argument wants to see
what `[12]` refers to without scrolling to the back, and an entry that carries an arXiv id or a
DOI can be added to the library in one action — which is how a bibliography becomes a reading
list rather than a wall of names.

Two citation styles cover nearly all of it. Numbered entries begin `[12]` or `12.`; author-year
entries begin with a surname and a year in brackets. Anything else is left as one entry rather
than guessed at, because a wrongly split reference is worse than an unsplit one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_ENTRY_LENGTH = 20
MAX_ENTRIES = 300

# `[12]` or `12.` at the start of a line, which is where a numbered entry begins.
_NUMBERED_START = re.compile(r"^\s*(?:\[(\d{1,3})\]|(\d{1,3})\.)\s+(?=\S)")

# Two author-year shapes, because the fields differ:
#   `Vaswani, A., et al. (2017).`  — the year in brackets
#   `Alan Akbik, Duncan Blythe, and Roland Vollgraf. 2018. Contextual…` — the ACL style, where
#   the year is its own sentence. Missing this one reduced a 100-entry bibliography to a single
#   entry, which is how it was found.
#   Author initials carry periods — "Abramson, J., Ahuja, A., …" — so the span before the year
#   cannot exclude them, only bound its length. Excluding them matched nothing on a paper whose
#   author lists run to a dozen names, and turned a 100-entry bibliography into one entry.
_AUTHOR_YEAR_START = re.compile(
    r"^\s*[A-Z][A-Za-z'’-]+,?\s.{0,200}?\((?:19|20)\d{2}[a-z]?\)"
    r"|^\s*[A-Z][A-Za-z'’-]+.{0,160}?\.\s+(?:19|20)\d{2}[a-z]?\."
)

_ARXIV = re.compile(r"arxiv[:\s/]*(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)
_ARXIV_LEGACY = re.compile(r"arxiv[:\s/]*([a-z-]+(?:\.[A-Z]{2})?/\d{7})", re.IGNORECASE)
_DOI = re.compile(r"\b(10\.\d{4,9}/[^\s\"'<>]*[^\s\"'<>.,;:)\]])", re.IGNORECASE)
_YEAR = re.compile(r"\b(19|20)\d{2}[a-z]?\b")


@dataclass(frozen=True, slots=True)
class DetectedReference:
    marker: str | None
    """The number the paper printed, when it printed one — what `[12]` in the body points at."""

    text: str
    arxiv_id: str | None
    doi: str | None
    year: int | None


def _identifiers(text: str) -> tuple[str | None, str | None]:
    arxiv = _ARXIV.search(text) or _ARXIV_LEGACY.search(text)
    doi = _DOI.search(text)
    return (arxiv.group(1) if arxiv else None, doi.group(1) if doi else None)


def _year_of(text: str) -> int | None:
    match = _YEAR.search(text)
    if not match:
        return None
    digits = re.search(r"\d{4}", match.group(0))
    return int(digits.group(0)) if digits else None


def parse_references(section_text: str) -> list[DetectedReference]:
    """Split a bibliography into entries.

    Lines are joined back into entries by looking for the *start* of each one rather than by
    guessing where the previous ended, because entries wrap unpredictably and a heuristic that
    splits on line endings produces one reference per line.
    """
    lines = [line.rstrip() for line in section_text.splitlines()]
    # The heading itself is not a reference.
    if lines and re.match(r"^\s*references?\b", lines[0], re.IGNORECASE):
        lines = lines[1:]

    starts = [
        index
        for index, line in enumerate(lines)
        if _NUMBERED_START.match(line) or _AUTHOR_YEAR_START.match(line)
    ]

    if not starts:
        joined = " ".join(line.strip() for line in lines if line.strip())
        if len(joined) < MIN_ENTRY_LENGTH:
            return []
        arxiv, doi = _identifiers(joined)
        return [
            DetectedReference(
                marker=None, text=joined, arxiv_id=arxiv, doi=doi, year=_year_of(joined)
            )
        ]

    entries: list[DetectedReference] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        block = " ".join(line.strip() for line in lines[start:end] if line.strip())

        match = _NUMBERED_START.match(block)
        marker = None
        if match:
            marker = match.group(1) or match.group(2)
            block = _NUMBERED_START.sub("", block, count=1)

        block = " ".join(block.split())
        if len(block) < MIN_ENTRY_LENGTH:
            continue

        arxiv, doi = _identifiers(block)
        entries.append(
            DetectedReference(
                marker=marker, text=block, arxiv_id=arxiv, doi=doi, year=_year_of(block)
            )
        )
        if len(entries) >= MAX_ENTRIES:
            break

    return entries
