"""Turning retrieved passages into the SOURCES block the model reads.

Two jobs: fit the passages into a token budget, and number them so a citation marker in the
answer maps back to a real chunk id. The numbering is the contract — `[2]` in the prose means
`sources[1]`, and the server resolves it rather than trusting the model to describe its own
source.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from atlas.ingestion.text import estimate_tokens
from atlas.retrieval.search import RetrievedChunk

DEFAULT_CONTEXT_TOKENS = 12_000
"""Budget for the SOURCES block. Generous — the models Atlas targets have large context
windows — but bounded, because an answer assembled from thirty marginal passages is worse
than one from eight good ones, and slower."""

_CITATION_MARKER = re.compile(r"\[(\d{1,2})\]")


@dataclass(frozen=True, slots=True)
class Source:
    """A numbered passage, as the model sees it."""

    marker: int
    chunk: RetrievedChunk

    def render(self) -> str:
        header = f"[{self.marker}] {self.chunk.paper_title}"
        if self.chunk.publication_year:
            header += f" ({self.chunk.publication_year})"
        if self.chunk.authors:
            first = self.chunk.authors[0]
            header += f" — {first}{' et al.' if len(self.chunk.authors) > 1 else ''}"
        return f"{header}\n{self.chunk.locator}\n{self.chunk.content}"


@dataclass(frozen=True, slots=True)
class Context:
    sources: list[Source]
    text: str
    token_estimate: int
    dropped: int
    """Passages retrieval found but the budget could not fit. Logged, never silently ignored."""

    @property
    def is_empty(self) -> bool:
        return not self.sources


def build_context(
    chunks: Sequence[RetrievedChunk], *, token_budget: int = DEFAULT_CONTEXT_TOKENS
) -> Context:
    """Number and render passages, in relevance order, until the budget is spent.

    Stops at the first passage that does not fit rather than skipping it to fit a smaller one
    later. Markers must ascend with relevance for the answer's numbering to be meaningful, and
    a gap in the sequence is confusing to both the model and the reader.
    """
    sources: list[Source] = []
    rendered: list[str] = []
    used = 0

    for index, chunk in enumerate(chunks, start=1):
        source = Source(marker=index, chunk=chunk)
        block = source.render()
        cost = estimate_tokens(block)
        if sources and used + cost > token_budget:
            break
        sources.append(source)
        rendered.append(block)
        used += cost

    return Context(
        sources=sources,
        text="\n\n---\n\n".join(rendered),
        token_estimate=used,
        dropped=len(chunks) - len(sources),
    )


def compose_user_turn(question: str, context: Context) -> str:
    """The user turn: the question, plus the sources the model may draw on.

    Sources are placed before the question so the stable part of the prompt comes first, and
    so the question is the last thing the model reads.
    """
    if context.is_empty:
        return (
            "SOURCES\nNone. Nothing in the user's library matched this question.\n\n"
            f"QUESTION\n{question}\n\n"
            "Tell the user their library does not contain material on this, and say what "
            "would answer it. Do not answer from general knowledge as though it were "
            "sourced."
        )

    return f"SOURCES\n{context.text}\n\nQUESTION\n{question}"


def markers_used(answer: str, *, available: int) -> set[int]:
    """Which citation markers the answer actually referenced.

    Markers outside the available range are discarded: the model occasionally writes `[9]`
    when five sources were supplied, and rendering a citation for a source that was never
    retrieved is exactly the fabrication Atlas exists to avoid. This is a safety net — the
    citations attached to a message come from the retrieval result, not from this parse.
    """
    return {
        marker
        for match in _CITATION_MARKER.finditer(answer)
        if 1 <= (marker := int(match.group(1))) <= available
    }
