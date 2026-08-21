"""Searching the catalog, and importing from it into a library.

Two operations with very different costs. Search touches one indexed table and returns in
milliseconds regardless of how many papers the catalog holds. Import downloads a PDF, parses
it, chunks it, and embeds every chunk — seconds of work and a network round trip to arXiv — so
it is rate limited and its result is a queued job rather than a finished paper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Select, and_, desc, func, literal, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.core.errors import NotFoundError
from atlas.core.logging import get_logger
from atlas.models.catalog import CatalogPaper
from atlas.models.paper import Paper, PaperSource
from atlas.models.user import User
from atlas.services.paper_service import PaperService, UploadResult

logger = get_logger(__name__)

COUNT_CEILING = 1_000
"""How far the result counter goes before it gives up and says "more than this".

A `count(*)` over a text search is proportional to how many rows *match*, not how many are
returned, and a broad word in a large catalog matches a great many. Counting them exactly
costs more than finding the ten results anyone is going to look at, and buys a number no one
reads past the first digit. So the count stops at a ceiling and the response says whether it
is exact — which is what every search engine does, and for the same reason.
"""


@dataclass(frozen=True, slots=True)
class CatalogSearchResult:
    items: list[CatalogPaper]
    total: int
    total_is_exact: bool
    limit: int
    offset: int


@dataclass(frozen=True, slots=True)
class CategoryCount:
    category: str
    count: int


@dataclass(frozen=True, slots=True)
class CatalogStats:
    total: int
    with_abstract: int
    earliest_year: int | None
    latest_year: int | None
    top_categories: list[CategoryCount] = field(default_factory=list)


class CatalogService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    def _filtered(
        self, statement: Select, *, category: str | None, year_from: int | None, year_to: int | None
    ) -> Select:
        """Apply the filters that do not depend on a query being present."""
        if category:
            # Containment against the whole category list, not equality against the primary
            # one: a paper cross-listed into cs.LG belongs in cs.LG as far as a reader is
            # concerned, and the GIN index on `categories` serves exactly this operator.
            statement = statement.where(CatalogPaper.categories.contains([category]))
        if year_from is not None:
            statement = statement.where(CatalogPaper.published_on >= _january(year_from))
        if year_to is not None:
            statement = statement.where(CatalogPaper.published_on <= _december(year_to))
        return statement

    async def search(
        self,
        *,
        query: str | None = None,
        category: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
        sort: str = "relevance",
        limit: int = 20,
        offset: int = 0,
    ) -> CatalogSearchResult:
        """Ranked search over titles and abstracts.

        `websearch_to_tsquery` parses the query, not `to_tsquery`. It understands the syntax
        people actually type into a search box — quoted phrases, `or`, a leading `-` to
        exclude — and, crucially, it **never raises on malformed input**. `to_tsquery` treats
        its argument as an expression and rejects a stray operator with a syntax error, which
        from a web search box means a trailing `&` or an unbalanced quote returns a 500.
        """
        cleaned = (query or "").strip()

        statement = select(CatalogPaper)
        # `literal(1)` because nothing reads the value — only the number of rows matters, and
        # selecting a constant lets PostgreSQL answer from the index without touching the heap.
        counter = select(literal(1)).select_from(CatalogPaper)

        rank = None
        if cleaned:
            tsquery = func.websearch_to_tsquery("english", cleaned)
            match = CatalogPaper.search_tsv.op("@@")(tsquery)
            statement = statement.where(match)
            counter = counter.where(match)
            # `ts_rank_cd` rather than `ts_rank`: it accounts for how close the matched terms
            # are to each other, so a paper whose abstract says "graph neural network" ranks
            # above one that mentions graphs in one sentence and networks in another.
            rank = func.ts_rank_cd(CatalogPaper.search_tsv, tsquery)

        statement = self._filtered(
            statement, category=category, year_from=year_from, year_to=year_to
        )
        counter = self._filtered(counter, category=category, year_from=year_from, year_to=year_to)

        newest = (CatalogPaper.published_on.desc().nulls_last(), CatalogPaper.arxiv_id.desc())
        if sort == "newest" or rank is None:
            # With no query there is nothing to rank by, so recency is the only sensible
            # order — and it is what someone browsing a field expects to see first.
            statement = statement.order_by(*newest)
        else:
            # `arxiv_id` breaks ties last. Without a total order, two rows of equal rank and
            # equal date can swap places between pages, which shows the same paper twice and
            # hides another entirely.
            statement = statement.order_by(desc(rank), *newest)

        items = list(
            (await self._db.execute(statement.limit(limit).offset(offset))).scalars().all()
        )

        # Counting is bounded by a subquery with its own LIMIT, so PostgreSQL stops scanning
        # once the ceiling is reached instead of counting every match. The subquery yields one
        # row per match — an inner query that returned the count itself would be limited to a
        # single row, and the answer would always be 1.
        bounded = counter.limit(COUNT_CEILING).subquery()
        total = int(
            (await self._db.execute(select(func.count()).select_from(bounded))).scalar_one()
        )

        return CatalogSearchResult(
            items=items,
            total=total,
            total_is_exact=total < COUNT_CEILING,
            limit=limit,
            offset=offset,
        )

    async def get(self, catalog_id: uuid.UUID) -> CatalogPaper:
        paper = await self._db.get(CatalogPaper, catalog_id)
        if paper is None:
            raise NotFoundError("That paper isn't in the catalog.")
        return paper

    async def imported_ids(
        self, owner_id: uuid.UUID, catalog_papers: list[CatalogPaper]
    ) -> set[str]:
        """Which of these the user already has, as arXiv ids.

        One query for the whole page rather than one per result. The Discover page needs this
        for every row it renders, and asking per row is the N+1 that makes a search results
        page slow in exactly the way `tests/test_query_counts.py` exists to catch.
        """
        wanted = [paper.arxiv_id for paper in catalog_papers]
        if not wanted:
            return set()
        rows = await self._db.execute(
            select(Paper.arxiv_id).where(
                and_(Paper.owner_id == owner_id, Paper.arxiv_id.in_(wanted))
            )
        )
        return {value for value in rows.scalars().all() if value}

    async def import_paper(
        self, *, owner: User, catalog_id: uuid.UUID, papers: PaperService
    ) -> UploadResult:
        """Fetch the real PDF and ingest it as an ordinary paper.

        This deliberately goes through `add_from_identifier`, the same path the "add by
        reference" box uses, rather than a shortcut of its own. That means the download is
        subject to the same SSRF checks, the file is validated by its bytes, identical files
        deduplicate against the existing library, and ingestion is the same pipeline an upload
        gets. A catalog import produces a paper with nothing special about it — which is the
        point, because everything downstream (the reader, retrieval, citations) then works
        without knowing where the paper came from.

        The catalog's metadata is copied onto the paper before the transaction commits. The
        pipeline only fills fields that are still empty, so arXiv's curated title and author
        list take precedence over what heuristic extraction would guess from the PDF's first
        page — which is a real improvement, since that guess is wrong often enough that the
        code that makes it says so.
        """
        entry = await self.get(catalog_id)

        result = await papers.add_from_identifier(owner=owner, reference=entry.arxiv_id)

        if not result.already_existed:
            paper = result.paper
            paper.title = entry.title[:1000]
            paper.authors = entry.authors
            paper.abstract = entry.abstract
            paper.arxiv_id = entry.arxiv_id[:64]
            paper.source = PaperSource.arxiv
            paper.source_url = entry.abs_url
            if entry.doi:
                paper.doi = entry.doi[:255]
            if entry.published_on:
                paper.publication_year = entry.published_on.year
            if entry.journal_ref:
                paper.venue = entry.journal_ref
            await self._db.flush()

        logger.info(
            "imported a paper from the catalog",
            extra={
                "arxiv_id": entry.arxiv_id,
                "paper_id": str(result.paper.id),
                "already_existed": result.already_existed,
            },
        )
        return result

    async def stats(self) -> CatalogStats:
        """A summary for the Discover page's header.

        The category counts come from `jsonb_array_elements_text`, which expands every paper's
        category list into rows and groups them. It is a full scan and there is no index that
        helps, so it is limited to the top ten and is the reason this is a separate endpoint
        the page can render around rather than part of every search response.
        """
        totals = (
            await self._db.execute(
                select(
                    func.count(),
                    func.count(CatalogPaper.abstract),
                    func.min(func.extract("year", CatalogPaper.published_on)),
                    func.max(func.extract("year", CatalogPaper.published_on)),
                ).select_from(CatalogPaper)
            )
        ).one()

        # `column_valued` makes the set-returning function a FROM entry in its own right.
        # Because its argument references `CatalogPaper.categories`, PostgreSQL joins it
        # laterally against each row — which is what expands one paper's category list into
        # one row per category, ready to group.
        # `jsonb_array_elements_text` returns a set, so joining it against the table expands
        # one paper's category list into one row per category, ready to group. The join
        # condition is `true` because the association is already made by the function's
        # argument — writing it explicitly rather than as an implicit comma join keeps
        # SQLAlchemy from warning about a cartesian product it is not looking at.
        categories = func.jsonb_array_elements_text(CatalogPaper.categories).table_valued("value")
        rows = await self._db.execute(
            select(categories.c.value, func.count().label("n"))
            .select_from(CatalogPaper)
            .join(categories, true())
            .group_by(categories.c.value)
            .order_by(desc("n"))
            .limit(10)
        )

        return CatalogStats(
            total=int(totals[0]),
            with_abstract=int(totals[1]),
            earliest_year=int(totals[2]) if totals[2] is not None else None,
            latest_year=int(totals[3]) if totals[3] is not None else None,
            top_categories=[
                CategoryCount(category=str(name), count=int(count)) for name, count in rows
            ],
        )


def _january(year: int) -> date:
    """The first day of the year, as a `date`.

    Not an ISO string. asyncpg binds parameters by their Python type and does not coerce text
    to a date the way a string-substituting driver would, so a string here reaches PostgreSQL
    as `character varying` and `date >= character varying` has no operator — a 500 on any
    search that sets a year bound.
    """
    return date(year, 1, 1)


def _december(year: int) -> date:
    return date(year, 12, 31)
