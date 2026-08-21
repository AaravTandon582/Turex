"""Reordering fused results before they become an answer.

Rank fusion combines two rankings that disagree, and it does so without ever looking at the
passages themselves — only at their positions. That leaves signal on the table: whether the
query's terms actually appear together, whether the passage is a substantial paragraph or a
caption, whether it sits in a section that tends to answer questions.

This is a *lexical* reranker, not a cross-encoder. That is a deliberate limit: a cross-encoder
would score meaning rather than words, but it needs a model, a download, and inference time on
every search. What is here costs microseconds and no dependency, and it is measured — the
benchmark says whether it earns its place, and the numbers are in `docs/evaluation.md`.

Retrieval asks for more candidates than the caller wants so this has something to reorder.
Reranking the final eight would only shuffle them.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

CANDIDATE_MULTIPLIER = 3
"""How many candidates to fetch per result returned. Enough to give reranking room, small
enough that the extra rows cost nothing measurable."""

PRIOR_WEIGHT = 0.35
"""How much the fused position counts against what the passage actually says.

The fused order carries the vector model's judgement, which word matching cannot reproduce, so
it leads. It does not decide: at this weight a clearly better passage further down can still
come first."""

IDEAL_LENGTH = 900
"""Characters. Around a substantial paragraph: long enough to contain a claim with its
qualifiers, short enough not to be three unrelated ones."""

# Sections that tend to hold the answer to a question about what a paper did or found.
_STRONG_SECTIONS = re.compile(
    r"\b(method|methods|approach|architecture|model|results?|experiments?|evaluation|"
    r"analysis|abstract|introduction|discussion)\b",
    re.IGNORECASE,
)

# Sections that rarely answer anything, even when they mention the query's words.
_WEAK_SECTIONS = re.compile(
    r"\b(acknowledge?ments?|appendix|references|bibliography|related work|broader impact)\b",
    re.IGNORECASE,
)

_WORD = re.compile(r"[a-z0-9]+")

if TYPE_CHECKING:
    from turex.retrieval.search import RetrievedChunk


def _terms(text: str) -> list[str]:
    return _WORD.findall(text.lower())


@dataclass(frozen=True, slots=True)
class Signals:
    """Why a passage scored what it did. Kept separate so the score can be explained."""

    coverage: float
    """Share of the query's distinct terms that appear at all."""

    phrase: float
    """Whether a run of query terms appears intact — the strongest lexical evidence there is."""

    length: float
    section: float
    """A multiplier, not a term. "This is an acknowledgements section" should discount every
    other signal rather than subtract a little from the sum — the words being present there
    means less, not slightly less."""

    @property
    def total(self) -> float:
        content = 0.55 * self.coverage + 0.35 * self.phrase + 0.10 * self.length
        return content * self.section


def _phrase_score(query_terms: list[str], content_terms: list[str]) -> float:
    """The longest run of consecutive query terms found in the passage, as a share of the query.

    A passage containing "scaled dot product attention" in that order is answering about scaled
    dot-product attention. One containing those four words scattered across a page is probably
    not, and coverage alone cannot tell them apart.
    """
    if not query_terms or not content_terms:
        return 0.0

    longest = 0
    positions = {term: index for index, term in enumerate(content_terms)}
    for start in range(len(query_terms)):
        run = 0
        cursor: int | None = None
        for term in query_terms[start:]:
            index = positions.get(term)
            if index is None or (cursor is not None and index != cursor + 1):
                break
            run += 1
            cursor = index
        longest = max(longest, run)

    return longest / len(query_terms)


def _length_score(content: str) -> float:
    """Favour a substantial paragraph. Falls away smoothly in both directions."""
    if not content:
        return 0.0
    ratio = len(content) / IDEAL_LENGTH
    return math.exp(-abs(math.log(ratio))) if ratio > 0 else 0.0


def _section_score(section_title: str | None) -> float:
    """A multiplier on everything else. Unknown sections are not penalised much — most of a
    paper is neither obviously strong nor obviously weak, and guessing there would hurt."""
    if not section_title:
        return 0.8
    if _WEAK_SECTIONS.search(section_title):
        return 0.35
    if _STRONG_SECTIONS.search(section_title):
        return 1.0
    return 0.8


def score_passage(query: str, content: str, section_title: str | None) -> Signals:
    query_terms = [term for term in _terms(query) if len(term) > 2]
    content_terms = _terms(content)
    present = set(content_terms)

    coverage = (
        sum(1 for term in set(query_terms) if term in present) / len(set(query_terms))
        if query_terms
        else 0.0
    )

    return Signals(
        coverage=coverage,
        phrase=_phrase_score(query_terms, content_terms),
        length=_length_score(content),
        section=_section_score(section_title),
    )


def rerank(query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Reorder fused candidates using the passages themselves.

    Fusion is blind to content — it combines two rankings by position. This looks at whether
    the query's terms actually appear, whether they appear *together*, and what kind of section
    the passage sits in.

    The fused position is kept as a signal rather than discarded: it carries the vector model's
    judgement, which no amount of word matching reproduces. Reranking adjusts that order, it
    does not replace it.
    """
    if len(candidates) <= 1:
        return candidates

    scored: list[tuple[float, int, RetrievedChunk]] = []
    for position, chunk in enumerate(candidates):
        signals = score_passage(query, chunk.content, chunk.section_title)

        # A logarithmic discount, not a reciprocal one. `1/(1+position)` halves between the
        # first and second result, a gap no content signal can close — which made reranking a
        # no-op in measurement. This decays gently enough that the fused order still leads
        # while remaining possible to overturn.
        prior = 1.0 / math.log2(position + 2)
        scored.append((PRIOR_WEIGHT * prior + (1 - PRIOR_WEIGHT) * signals.total, position, chunk))

    # Position breaks ties, so an equal score never reorders arbitrarily between runs.
    scored.sort(key=lambda row: (-row[0], row[1]))
    return [chunk for _, _, chunk in scored]
