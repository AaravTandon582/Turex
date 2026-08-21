"""Discovery endpoints: recommendations, the knowledge graph, and the dashboard."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel

from turex.api.deps import CurrentUser, DbDep
from turex.services.discovery_service import GraphService, RecommendationService

router = APIRouter(tags=["discovery"])


class RecommendationRead(BaseModel):
    paper_id: str
    title: str
    authors: list[str]
    publication_year: int | None
    reason: str
    related_to_id: str | None
    related_to_title: str | None


class GraphNodeRead(BaseModel):
    id: str
    kind: str
    label: str
    weight: int
    entity_id: str | None


class GraphEdgeRead(BaseModel):
    source: str
    target: str
    kind: str


class GraphRead(BaseModel):
    nodes: list[GraphNodeRead]
    edges: list[GraphEdgeRead]


@router.get("/recommendations", response_model=list[RecommendationRead])
async def recommendations(
    user: CurrentUser,
    db: DbDep,
    limit: Annotated[int, Query(ge=1, le=20)] = 6,
) -> list[RecommendationRead]:
    """What to read next, and why.

    Every recommendation carries the concrete reason it was made. A suggestion the reader
    cannot evaluate is one they learn to ignore.
    """
    results = await RecommendationService(db).recommend(owner=user, limit=limit)
    return [
        RecommendationRead(
            paper_id=str(entry.paper_id),
            title=entry.title,
            authors=entry.authors,
            publication_year=entry.publication_year,
            reason=entry.reason,
            related_to_id=str(entry.related_to_id) if entry.related_to_id else None,
            related_to_title=entry.related_to_title,
        )
        for entry in results
    ]


@router.get("/graph", response_model=GraphRead)
async def knowledge_graph(user: CurrentUser, db: DbDep) -> GraphRead:
    """Papers, the concepts they share, the projects gathering them, and open questions.

    Built from term overlap and the links the user has made — never from a model, so an edge
    always means two papers genuinely use the same term.
    """
    graph = await GraphService(db).build(owner=user)
    return GraphRead(
        nodes=[
            GraphNodeRead(
                id=node.id,
                kind=node.kind,
                label=node.label,
                weight=node.weight,
                entity_id=node.entity_id,
            )
            for node in graph.nodes
        ],
        edges=[
            GraphEdgeRead(source=edge.source, target=edge.target, kind=edge.kind)
            for edge in graph.edges
        ],
    )
