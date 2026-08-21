"""Catalog endpoints: searching millions of papers, and importing one into a library.

The catalog itself is not owner-scoped — arXiv's metadata is public and identical for
everybody — but these routes still require a session, like every other route in the API. The
reason is not secrecy: search is a database query someone else can make Atlas run, importing
copies a paper into a specific library, and both need an account to rate limit against.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response, status

from atlas.api.deps import CatalogServiceDep, CurrentUser, GuardDep, PaperServiceDep
from atlas.api.v1.papers import build_detail
from atlas.models.catalog import CatalogPaper
from atlas.schemas.catalog import (
    CatalogPage,
    CatalogPaperRead,
    CatalogStatsRead,
    CategoryCountRead,
)
from atlas.schemas.paper import PaperDetail
from atlas.security import policy

router = APIRouter(prefix="/catalog", tags=["catalog"])


def _read(entry: CatalogPaper, *, in_library: bool = False) -> CatalogPaperRead:
    return CatalogPaperRead(
        id=entry.id,
        source=entry.source.value,
        external_id=entry.external_id,
        doi=entry.doi,
        title=entry.title,
        abstract=entry.abstract,
        # Authors are read back defensively rather than trusted as-is. The column is JSONB
        # written by a harvester, so its shape is guaranteed by the code that wrote it and not
        # by the database — and a row that predates a change to that code would otherwise
        # break serialisation for the whole page it appears on.
        authors=[
            {"name": str(author["name"])}
            for author in entry.authors
            if isinstance(author, dict) and author.get("name")
        ],
        categories=[str(category) for category in entry.categories],
        primary_category=entry.primary_category,
        journal_ref=entry.journal_ref,
        comments=entry.comments,
        published_on=entry.published_on,
        updated_on=entry.updated_on,
        landing_url=entry.landing_url,
        pdf_url=entry.pdf_url,
        in_library=in_library,
    )


@router.get("/search", response_model=CatalogPage)
async def search_catalog(
    user: CurrentUser,
    service: CatalogServiceDep,
    guard: GuardDep,
    q: Annotated[
        str | None,
        Query(max_length=500, description="Words to look for in titles and abstracts"),
    ] = None,
    category: Annotated[
        str | None, Query(max_length=32, description="An arXiv category, e.g. cs.LG")
    ] = None,
    year_from: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    year_to: Annotated[int | None, Query(ge=1900, le=2200)] = None,
    sort: Annotated[str, Query(pattern="^(relevance|newest)$")] = "relevance",
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> CatalogPage:
    """Search the catalog by words in the title and abstract.

    Every argument is optional: with no query this browses the newest papers, which is what
    the Discover page shows before anyone has typed anything.

    `offset` is capped. Deep pagination makes PostgreSQL scan and discard every skipped row,
    so page five hundred costs five hundred pages of work to serve — and nobody reaches it by
    reading. Narrowing the query is both faster and what actually finds the paper.
    """
    await guard.by_user(user.id, policy.SEARCH_PER_USER, scope="search")

    found = await service.search(
        query=q,
        category=category,
        year_from=year_from,
        year_to=year_to,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    owned = await service.imported_ids(user.id, found.items)

    return CatalogPage(
        items=[_read(entry, in_library=entry.external_id in owned) for entry in found.items],
        total=found.total,
        total_is_exact=found.total_is_exact,
        limit=found.limit,
        offset=found.offset,
    )


@router.get("/stats", response_model=CatalogStatsRead)
async def catalog_stats(user: CurrentUser, service: CatalogServiceDep) -> CatalogStatsRead:
    """How big the catalog is and what is in it."""
    summary = await service.stats()
    return CatalogStatsRead(
        total=summary.total,
        by_source=summary.by_source,
        with_abstract=summary.with_abstract,
        earliest_year=summary.earliest_year,
        latest_year=summary.latest_year,
        top_categories=[
            CategoryCountRead(category=entry.category, count=entry.count)
            for entry in summary.top_categories
        ],
    )


@router.get("/{catalog_id}", response_model=CatalogPaperRead)
async def read_catalog_paper(
    catalog_id: uuid.UUID, user: CurrentUser, service: CatalogServiceDep
) -> CatalogPaperRead:
    entry = await service.get(catalog_id)
    owned = await service.imported_ids(user.id, [entry])
    return _read(entry, in_library=entry.external_id in owned)


@router.post(
    "/{catalog_id}/import",
    response_model=PaperDetail,
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_catalog_paper(
    catalog_id: uuid.UUID,
    user: CurrentUser,
    service: CatalogServiceDep,
    papers: PaperServiceDep,
    guard: GuardDep,
    response: Response,
) -> PaperDetail:
    """Download this paper's PDF and add it to the library.

    Answers the way an upload does: **202** when the paper is queued for ingestion, **200**
    when it is already in the library — importing the same paper twice is a thing people do,
    and the right response is to hand back the one they have rather than a second copy or an
    error.

    Rate limited against the upload budget rather than the search one. The work is an upload:
    a download from arXiv, a parse, and an embedding call per chunk. Counting it as a search
    would let a loop over search results run up hundreds of ingestions.
    """
    await guard.by_user(user.id, policy.UPLOADS_PER_USER, scope="upload")

    result = await service.import_paper(owner=user, catalog_id=catalog_id, papers=papers)
    if result.already_existed:
        response.status_code = status.HTTP_200_OK

    # The same assembly the library's own endpoints use, so an imported paper is described
    # identically to an uploaded one from the very first response.
    return await build_detail(papers, result.paper)
