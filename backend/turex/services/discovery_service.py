"""Surfacing what a library already contains but has not been asked.

Two features, both built from data Turex already has rather than from a model:

* **Recommendations** — which paper to read next, and *why*. Every recommendation carries the
  concrete reason it was made. A suggestion a user cannot evaluate is one they learn to
  ignore.
* **Knowledge graph** — the connections between papers, the concepts they share, and the
  questions being asked about them.

Neither calls a language model. Both are derived from embeddings, shared vocabulary, and the
links the user has already made, which means they work on an instance with no API key and
cannot invent a relationship that is not there.
"""

from __future__ import annotations

import math
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core.logging import get_logger
from turex.models.paper import Paper, PaperChunk, ProcessingStatus, ReadingStatus
from turex.models.user import User
from turex.models.workspace import Hypothesis, Project, ProjectPaper

logger = get_logger(__name__)

MIN_LIBRARY_FOR_RECOMMENDATIONS = 2
"""Below this there is nothing to compare against, and a recommendation would be noise."""

SIMILARITY_THRESHOLD = 0.25
"""Chosen from measurement, not intuition. On the offline embedder, two papers on the same
subject score around 0.41 and two unrelated ones around 0.10, so this sits with margin on both
sides. Note the offline embedder is lexical: it separates subjects but not subfields, so on an
instance without a real embedding provider these suggestions are coarse."""

CONCEPT_MIN_PAPERS = 2
"""A concept shared by one paper is not a connection; it is a word."""

MIN_TERM_FREQUENCY = 3
"""Total occurrences across the library. Document frequency alone lets through measurement
vocabulary — "percent", "median" — which two papers share without being about the same thing.
A term a paper is actually about gets repeated."""


# --------------------------------------------------------------------------------------
# Recommendations
# --------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Recommendation:
    paper_id: uuid.UUID
    title: str
    authors: list[str]
    publication_year: int | None
    reason: str
    """Why this paper, in the user's terms — always concrete, never "you might like this"."""

    related_to_id: uuid.UUID | None = None
    related_to_title: str | None = None
    score: float = 0.0


class RecommendationService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._vectors: dict[uuid.UUID, list[float] | None] = {}
        """Document vectors computed during this request. Without it the project pass
        recomputes the same paper's vector once per comparison — a query per pair."""

    async def recommend(self, *, owner: User, limit: int = 6) -> list[Recommendation]:
        """Papers worth reading next, each with the reason it surfaced.

        Ordered by how strong the reason is: an unread paper closely related to one being
        read now beats a generic "also in your library".
        """
        unread = await self._unread_papers(owner)
        if not unread:
            return []

        total = await self._db.scalar(
            select(func.count()).select_from(Paper).where(Paper.owner_id == owner.id)
        )
        if (total or 0) < MIN_LIBRARY_FOR_RECOMMENDATIONS:
            return []

        recommendations: list[Recommendation] = []
        seen: set[uuid.UUID] = set()

        for candidate in await self._similar_to_recent_reading(owner, unread):
            if candidate.paper_id not in seen:
                seen.add(candidate.paper_id)
                recommendations.append(candidate)

        for candidate in await self._related_to_open_projects(owner, unread):
            if candidate.paper_id not in seen:
                seen.add(candidate.paper_id)
                recommendations.append(candidate)

        # Anything still unread and unexplained gets the honest fallback reason.
        for paper in unread:
            if paper.id in seen or len(recommendations) >= limit:
                continue
            seen.add(paper.id)
            recommendations.append(
                Recommendation(
                    paper_id=paper.id,
                    title=paper.display_title,
                    authors=_author_names(paper),
                    publication_year=paper.publication_year,
                    reason="In your library and not read yet.",
                    score=0.1,
                )
            )

        return sorted(recommendations, key=lambda entry: -entry.score)[:limit]

    async def _unread_papers(self, owner: User) -> list[Paper]:
        rows = await self._db.scalars(
            select(Paper)
            .where(
                Paper.owner_id == owner.id,
                Paper.status == ProcessingStatus.ready,
                Paper.reading_status.in_([ReadingStatus.unread, ReadingStatus.revisit]),
            )
            .order_by(Paper.created_at.desc())
            .limit(50)
        )
        return list(rows)

    async def _similar_to_recent_reading(
        self, owner: User, unread: list[Paper]
    ) -> list[Recommendation]:
        """Unread papers whose content sits near something the user is reading now.

        Compared by mean chunk embedding — a cheap document-level vector that needs no extra
        storage and no extra model call.
        """
        anchors = list(
            await self._db.scalars(
                select(Paper)
                .where(
                    Paper.owner_id == owner.id,
                    Paper.status == ProcessingStatus.ready,
                    Paper.reading_status.in_([ReadingStatus.reading, ReadingStatus.read]),
                )
                .order_by(Paper.last_opened_at.desc().nullslast())
                .limit(3)
            )
        )
        if not anchors:
            return []

        unread_vectors = {
            paper.id: vector
            for paper in unread
            if (vector := await self._document_vector(paper.id)) is not None
        }
        if not unread_vectors:
            return []

        results: list[Recommendation] = []
        for anchor in anchors:
            anchor_vector = await self._document_vector(anchor.id)
            if anchor_vector is None:
                continue

            for paper in unread:
                vector = unread_vectors.get(paper.id)
                if vector is None:
                    continue
                similarity = _cosine(anchor_vector, vector)
                if similarity < SIMILARITY_THRESHOLD:
                    continue
                results.append(
                    Recommendation(
                        paper_id=paper.id,
                        title=paper.display_title,
                        authors=_author_names(paper),
                        publication_year=paper.publication_year,
                        reason=f"Covers similar ground to “{_shorten(anchor.display_title)}”, "
                        "which you have been reading.",
                        related_to_id=anchor.id,
                        related_to_title=anchor.display_title,
                        score=0.5 + similarity,
                    )
                )

        return results

    async def _related_to_open_projects(
        self, owner: User, unread: list[Paper]
    ) -> list[Recommendation]:
        """Unread papers close to what an active project has already gathered."""
        rows = await self._db.execute(
            select(Project, Paper)
            .join(ProjectPaper, ProjectPaper.project_id == Project.id)
            .join(Paper, Paper.id == ProjectPaper.paper_id)
            .where(Project.owner_id == owner.id, Project.status == "active")
            .limit(30)
        )

        by_project: dict[uuid.UUID, tuple[Project, list[Paper]]] = {}
        for project, paper in rows:
            by_project.setdefault(project.id, (project, []))[1].append(paper)

        results: list[Recommendation] = []
        unread_ids = {paper.id for paper in unread}

        for project, gathered in by_project.values():
            for member in gathered[:5]:
                member_vector = await self._document_vector(member.id)
                if member_vector is None:
                    continue
                for paper in unread:
                    if paper.id not in unread_ids:
                        continue
                    vector = await self._document_vector(paper.id)
                    if vector is None:
                        continue
                    similarity = _cosine(member_vector, vector)
                    if similarity < SIMILARITY_THRESHOLD:
                        continue
                    results.append(
                        Recommendation(
                            paper_id=paper.id,
                            title=paper.display_title,
                            authors=_author_names(paper),
                            publication_year=paper.publication_year,
                            reason=f"Related to “{_shorten(member.display_title)}” in your "
                            f"project “{_shorten(project.name)}”.",
                            related_to_id=member.id,
                            related_to_title=member.display_title,
                            score=0.7 + similarity,
                        )
                    )

        return results

    async def _document_vector(self, paper_id: uuid.UUID) -> list[float] | None:
        """A paper's mean chunk embedding, computed once per request.

        Averaging is crude next to a trained document encoder, but it needs no extra model,
        no extra storage, and is enough to tell "about the same subject" from "not".
        """
        if paper_id in self._vectors:
            return self._vectors[paper_id]

        vector = await self._compute_document_vector(paper_id)
        self._vectors[paper_id] = vector
        return vector

    async def _compute_document_vector(self, paper_id: uuid.UUID) -> list[float] | None:
        rows = await self._db.scalars(
            select(PaperChunk.embedding)
            .where(PaperChunk.paper_id == paper_id, PaperChunk.embedding.is_not(None))
            .limit(60)
        )
        vectors = [list(vector) for vector in rows if vector is not None]
        if not vectors:
            return None

        width = len(vectors[0])
        mean = [sum(vector[index] for vector in vectors) / len(vectors) for index in range(width)]
        norm = math.sqrt(sum(value * value for value in mean))
        return [value / norm for value in mean] if norm else None


# --------------------------------------------------------------------------------------
# Knowledge graph
# --------------------------------------------------------------------------------------


@dataclass(slots=True)
class GraphNode:
    id: str
    kind: str
    """`paper` · `concept` · `project` · `question`"""

    label: str
    weight: int = 1
    entity_id: str | None = None


@dataclass(slots=True)
class GraphEdge:
    source: str
    target: str
    kind: str
    """`mentions` · `gathered_in` · `asks`"""

    weight: int = 1


@dataclass(slots=True)
class KnowledgeGraph:
    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)


# Concepts are found by corpus statistics rather than by pattern-matching capitalisation.
# An earlier version looked for Title Case phrases and acronyms; on real papers that missed
# every lowercase domain term ("transformer inference", "quantisation") while matching across
# heading boundaries ("Abstract Transformer"). Document frequency is both simpler and right:
# a term is a *connection* precisely when several papers use it and not all of them do.

_WORD = re.compile(r"[a-z][a-z0-9-]{2,}")

MAX_CONCEPTS = 30
MAX_DOCUMENT_FREQUENCY = 0.7
"""A term in nearly every paper describes the library, not a link between two of its members."""

DOCUMENT_FREQUENCY_FLOOR = 5

OPENING_CHUNKS_PER_PAPER = 4
"""How much of each paper the concept scan reads. The abstract and the first passages carry
the paper's own vocabulary; the rest is mostly method detail and prior work."""
"""Below this many papers the ceiling is not applied at all.

With four papers, a 0.6 ceiling rounds down to two — which excludes exactly the terms three
papers share, the strongest connections in the graph. A frequency ceiling only means anything
once there are enough documents for "most of them" to be a meaningful quantity."""

# Written as one block of text rather than a list literal: formatted one word per line this
# runs to nearly 200 lines and becomes impossible to scan, which is exactly how words end up
# missing from it. Split at import time so no formatter can collapse it back.
_STOPWORD_TEXT = """
    the and for that this these those with from are was were been being have has had not
    but they them their there here when where which while who whom whose what how why
    can could may might will would shall should must into over under between across
    through during before after above below than then also such some any all each both
    few more most other others another same only very much many several various one two
    three first second next last new old high low large small
    using used use uses show shows shown seen give gives given make makes made take takes
    work works based result results method methods approach approaches paper papers
    study studies model models data set sets task tasks case cases time times number
    numbers figure table section appendix example examples note notes well like just even
    still however moreover therefore thus hence although though because since about
    respectively via per within without toward towards
    abstract introduction conclusion conclusions discussion background related
    experiments evaluation analysis acknowledgements references
    arxiv preprint proceedings conference journal volume pages doi
    google microsoft openai deepmind meta facebook amazon nvidia
    university institute laboratory department research
"""

_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _terms_of(text: str) -> Counter[str]:
    """Unigrams and bigrams of content words, with their frequencies."""
    words = [
        word for word in _WORD.findall(text.lower()) if word not in _STOPWORDS and len(word) >= 4
    ]

    counts: Counter[str] = Counter(words)
    # Bigrams catch the phrases that carry a field's actual concepts — "attention mechanism",
    # "sequence alignment" — which single words split apart.
    counts.update(f"{first} {second}" for first, second in pairwise(words))
    return counts


class GraphService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def build(self, *, owner: User, max_papers: int = 40) -> KnowledgeGraph:
        """Assemble the graph from papers, the concepts they share, and open questions.

        Concepts come from term frequency across papers rather than from a model. That keeps
        the graph honest: an edge exists because two papers genuinely use the same term, not
        because something inferred a connection.
        """
        papers = list(
            await self._db.scalars(
                select(Paper)
                .where(Paper.owner_id == owner.id, Paper.status == ProcessingStatus.ready)
                .order_by(Paper.created_at.desc())
                .limit(max_papers)
            )
        )
        if not papers:
            return KnowledgeGraph()

        graph = KnowledgeGraph()
        for paper in papers:
            graph.nodes.append(
                GraphNode(
                    id=f"paper:{paper.id}",
                    kind="paper",
                    label=_shorten(paper.display_title, 70),
                    entity_id=str(paper.id),
                    weight=2,
                )
            )

        await self._add_concepts(graph, [paper.id for paper in papers])
        await self._add_projects(graph, owner, {paper.id for paper in papers})
        await self._add_questions(graph, owner)

        logger.info(
            "knowledge graph built",
            extra={"nodes": len(graph.nodes), "edges": len(graph.edges)},
        )
        return graph

    async def _add_concepts(self, graph: KnowledgeGraph, paper_ids: list[uuid.UUID]) -> None:
        """Terms several papers share, but not all of them, become concept nodes."""
        papers_by_term: defaultdict[str, set[uuid.UUID]] = defaultdict(set)
        frequency: Counter[str] = Counter()

        # Abstract and opening passages: dense in the paper's own vocabulary, and far cheaper
        # to scan than the whole document. Fetched for every paper in one statement — a query
        # per paper is invisible at four papers and four hundred queries at four hundred.
        positioned = (
            select(
                PaperChunk.paper_id,
                PaperChunk.content,
                func.row_number()
                .over(partition_by=PaperChunk.paper_id, order_by=PaperChunk.ordinal)
                .label("position"),
            )
            .where(PaperChunk.paper_id.in_(paper_ids))
            .subquery()
        )
        opening = await self._db.execute(
            select(positioned.c.paper_id, positioned.c.content).where(
                positioned.c.position <= OPENING_CHUNKS_PER_PAPER
            )
        )

        text_by_paper: defaultdict[uuid.UUID, list[str]] = defaultdict(list)
        for paper_id, content in opening:
            text_by_paper[paper_id].append(content)

        for paper_id, contents in text_by_paper.items():
            for term, count in _terms_of(" ".join(contents)).items():
                papers_by_term[term].add(paper_id)
                frequency[term] += count

        ceiling = (
            len(paper_ids)
            if len(paper_ids) < DOCUMENT_FREQUENCY_FLOOR
            else max(CONCEPT_MIN_PAPERS, math.floor(len(paper_ids) * MAX_DOCUMENT_FREQUENCY))
        )
        shared = {
            term: ids
            for term, ids in papers_by_term.items()
            if CONCEPT_MIN_PAPERS <= len(ids) <= ceiling and frequency[term] >= MIN_TERM_FREQUENCY
        }

        # Most-connective first, then two-word phrases, then most-used. Bigrams are ranked
        # above single words because "language model" identifies a subject where "model" does
        # not — an unqualified noun is the kind of node that makes a graph look busy and say
        # nothing.
        ranked = sorted(
            shared.items(),
            key=lambda item: (-len(item[1]), " " not in item[0], -frequency[item[0]]),
        )

        for term, ids in ranked[:MAX_CONCEPTS]:
            node_id = f"concept:{term}"
            graph.nodes.append(GraphNode(id=node_id, kind="concept", label=term, weight=len(ids)))
            for paper_id in ids:
                graph.edges.append(
                    GraphEdge(source=f"paper:{paper_id}", target=node_id, kind="mentions")
                )

    async def _add_projects(
        self, graph: KnowledgeGraph, owner: User, known_papers: set[uuid.UUID]
    ) -> None:
        rows = await self._db.execute(
            select(Project, ProjectPaper.paper_id)
            .outerjoin(ProjectPaper, ProjectPaper.project_id == Project.id)
            .where(Project.owner_id == owner.id)
        )

        seen: set[uuid.UUID] = set()
        for project, paper_id in rows:
            node_id = f"project:{project.id}"
            if project.id not in seen:
                seen.add(project.id)
                graph.nodes.append(
                    GraphNode(
                        id=node_id,
                        kind="project",
                        label=_shorten(project.name, 50),
                        entity_id=str(project.id),
                        weight=3,
                    )
                )
            if paper_id and paper_id in known_papers:
                graph.edges.append(
                    GraphEdge(source=node_id, target=f"paper:{paper_id}", kind="gathered_in")
                )

    async def _add_questions(self, graph: KnowledgeGraph, owner: User) -> None:
        """Open hypotheses, joined to the project asking them."""
        rows = await self._db.scalars(
            select(Hypothesis)
            .where(
                Hypothesis.owner_id == owner.id,
                Hypothesis.status.in_(["proposed", "testing"]),
            )
            .limit(20)
        )
        for hypothesis in rows:
            node_id = f"question:{hypothesis.id}"
            graph.nodes.append(
                GraphNode(
                    id=node_id,
                    kind="question",
                    label=_shorten(hypothesis.statement, 60),
                    entity_id=str(hypothesis.id),
                )
            )
            if hypothesis.project_id:
                graph.edges.append(
                    GraphEdge(
                        source=f"project:{hypothesis.project_id}", target=node_id, kind="asks"
                    )
                )


def _cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


def _author_names(paper: Paper) -> list[str]:
    return [str(author.get("name", "")) for author in (paper.authors or []) if author.get("name")]


def _shorten(value: str, limit: int = 45) -> str:
    collapsed = " ".join(value.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[:limit].rsplit(' ', 1)[0]}…"
