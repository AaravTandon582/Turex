"""Harvesting from OpenAlex — the papers arXiv does not have.

arXiv is preprints, and overwhelmingly physics, mathematics and computer science. It has no
medicine, no chemistry, no biology outside quantitative biology, and no humanities at all. A
catalog built only on it answers "find me a paper about transformers" and cannot answer "find
me a paper about statins", which is not a gap you can tune your way out of.

OpenAlex indexes over a hundred million works across every field, free and without a key.
That is far more than any single machine should hold — at the ~3.4KB a catalog row costs, a
hundred million is three hundred gigabytes — so this harvests *slices*: a field, a date range,
a topic. Which slices is the operator's decision, and `scripts/harvest_openalex.py` takes the
filter directly.

Two things differ from the arXiv feed and drive the shape of this module:

**Abstracts arrive inverted.** OpenAlex distributes an `abstract_inverted_index` — a map from
each word to the positions it occupies — rather than the text, for licensing reasons. It is
losslessly reversible and `_reconstruct` does so.

**Not every work has a file.** An arXiv id always resolves to a free PDF. An OpenAlex work
resolves to one only when it is open access, so `pdf_url` is nullable here, and a paper
without one is shown as something to read at the publisher rather than something to import.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.catalog.harvest import MAXIMUM_BACKOFF_SECONDS, TRANSIENT_STATUSES, HarvestProgress
from atlas.catalog.records import HarvestError
from atlas.core.logging import get_logger
from atlas.models.catalog import CatalogPaper, CatalogSource

logger = get_logger(__name__)

OPENALEX_ENDPOINT = "https://api.openalex.org/works"

PAGE_SIZE = 200
"""The most OpenAlex serves per request."""

MINIMUM_DELAY_SECONDS = 0.2
"""OpenAlex's polite pool allows ten requests a second. Half that is a comfortable margin and
still moves at a thousand papers a second, which is faster than the database can absorb.
"""

SELECT_FIELDS = ",".join(
    (
        "id",
        "doi",
        "title",
        "publication_year",
        "publication_date",
        "authorships",
        "primary_location",
        "open_access",
        "best_oa_location",
        "abstract_inverted_index",
        "topics",
        "type",
    )
)
"""Asked for explicitly. A full OpenAlex work is a large document — every citation, every
concept score, every location — and requesting only what is stored cuts the response by an
order of magnitude, which at a thousand pages is the difference between minutes and hours.
"""


@dataclass(frozen=True, slots=True)
class OpenAlexRecord:
    """One work, in the shape the catalog stores."""

    external_id: str
    title: str
    abstract: str | None = None
    authors: list[dict[str, Any]] | None = None
    topics: list[str] | None = None
    doi: str | None = None
    journal_ref: str | None = None
    published_on: date | None = None
    pdf_url: str | None = None
    landing_url: str | None = None


def _reconstruct(inverted: dict[str, list[int]] | None) -> str | None:
    """Turn OpenAlex's inverted index back into the abstract.

    The index maps each word to the positions it occupies, so laying the words back out by
    position recovers the original text exactly. It is distributed this way for licensing
    reasons rather than technical ones.

    A position appearing twice, or a gap, would mean a malformed index; the result is still
    the best available reading of it rather than nothing, since a slightly wrong abstract is
    far more useful for search than an absent one.
    """
    if not inverted:
        return None

    positioned: list[tuple[int, str]] = []
    for word, places in inverted.items():
        positioned.extend((place, word) for place in places)

    if not positioned:
        return None

    positioned.sort()
    return " ".join(word for _, word in positioned) or None


def _bare_id(url: str | None) -> str | None:
    """`https://openalex.org/W2741809807` → `W2741809807`.

    Stored bare so the column holds an identifier rather than a URL that will change if
    OpenAlex ever moves. The URL is reconstructible; the reverse is not.
    """
    if not url:
        return None
    return url.rstrip("/").rpartition("/")[2] or None


_NEVER_A_FILE = ("doi.org/", "dx.doi.org/", "handle.net/", "hdl.handle.net/")
"""URL shapes that are resolvers by definition, whatever field they arrive in.

OpenAlex's `pdf_url` is *usually* a direct file and occasionally a DOI link, which is a
redirect to a publisher's landing page and never bytes. Dropping those is not a guess about a
publisher's URL scheme — it is what a DOI is.

It does not catch everything: a publisher's own landing page can look exactly like its PDF
URL, and some hosts answer 403 to anything without a browser. The real guarantee is downstream,
where the import validates the bytes and refuses anything that is not a PDF; this only stops
the card offering a button for links that cannot possibly work.
"""


def _direct_file(url: str | None) -> str | None:
    if not url:
        return None
    lowered = url.lower()
    if any(marker in lowered for marker in _NEVER_A_FILE):
        return None
    return url


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        return None


def parse_work(work: dict[str, Any]) -> OpenAlexRecord | None:
    """One work, or None if it cannot be stored.

    A work with no id or no title has nothing to key on and nothing to show, which OpenAlex
    does produce — it indexes records from sources that themselves have gaps.
    """
    external_id = _bare_id(work.get("id"))
    title = (work.get("title") or "").strip()
    if not external_id or not title:
        return None

    location = work.get("primary_location") or {}
    source = location.get("source") or {}
    access = work.get("open_access") or {}
    best = work.get("best_oa_location") or {}

    doi = work.get("doi")
    if isinstance(doi, str):
        # Stored bare, as `Paper.doi` holds it, rather than as a resolver URL.
        doi = doi.replace("https://doi.org/", "").strip() or None

    return OpenAlexRecord(
        external_id=external_id,
        title=title[:2000],
        abstract=_reconstruct(work.get("abstract_inverted_index")),
        authors=[
            {"name": name}
            for entry in (work.get("authorships") or [])
            if (name := ((entry.get("author") or {}).get("display_name") or "").strip())
        ],
        # OpenAlex topics stand in for arXiv categories. They are not the same vocabulary, and
        # the column is deliberately named for the general idea rather than either scheme.
        topics=[
            name
            for topic in (work.get("topics") or [])
            if (name := (topic.get("display_name") or "").strip())
        ],
        doi=doi if isinstance(doi, str) else None,
        journal_ref=(source.get("display_name") or None),
        published_on=_parse_date(work.get("publication_date")),
        # `best_oa_location.pdf_url` rather than `open_access.oa_url`.
        #
        # They look interchangeable and are not: `oa_url` is "the best available URL", which is
        # frequently a landing page, while `pdf_url` is present only when OpenAlex knows of a
        # direct file. Using the former meant the card offered "Add to library" on papers that
        # could not be imported, and the download came back with a web page — measured at two
        # in six on a sample of open-access works.
        #
        # A null here is not a loss. It is the difference between a button that works and a
        # button that apologises, and the card says "No free full text" instead.
        pdf_url=_direct_file(best.get("pdf_url")),
        landing_url=(
            best.get("landing_page_url")
            or location.get("landing_page_url")
            or access.get("oa_url")
            or (f"https://doi.org/{doi}" if doi else None)
        ),
    )


class OpenAlexHarvester:
    """Reads pages of works, following OpenAlex's cursor."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str = OPENALEX_ENDPOINT,
        mailto: str | None = None,
        min_delay: float = MINIMUM_DELAY_SECONDS,
        max_attempts: int = 8,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._mailto = mailto
        self._min_delay = min_delay
        self._max_attempts = max_attempts

    async def _get(self, params: dict[str, str]) -> dict[str, Any]:
        delay = max(self._min_delay, 1.0)
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get(self._endpoint, params=params)
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts:
                    raise HarvestError(f"the request failed: {type(exc).__name__}") from exc
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAXIMUM_BACKOFF_SECONDS)
                continue

            if response.status_code in TRANSIENT_STATUSES or response.status_code == 429:
                if attempt == self._max_attempts:
                    raise HarvestError(
                        f"OpenAlex stayed unavailable after {attempt} attempts "
                        f"(HTTP {response.status_code}). Its daily limit resets on the hour; "
                        f"resume then."
                    )
                # A rate limit is the service saying how long to wait, so the header wins over
                # any schedule invented here. Without it a harvest either gives up too early
                # or hammers a limit that has already told it the answer.
                wait = _retry_after(response) or delay
                logger.info(
                    "openalex asked us to wait",
                    extra={"status": response.status_code, "seconds": wait},
                )
                await asyncio.sleep(wait)
                delay = min(delay * 2, MAXIMUM_BACKOFF_SECONDS)
                continue

            if response.status_code >= 400:
                raise HarvestError(f"HTTP {response.status_code}: {response.text[:300].strip()}")

            try:
                body: dict[str, Any] = response.json()
            except ValueError as exc:
                raise HarvestError("OpenAlex returned something that is not JSON") from exc
            return body

        raise HarvestError("ran out of attempts")

    async def pages(
        self,
        *,
        query: str | None = None,
        filters: str | None = None,
        resume_from: str | None = None,
    ) -> AsyncIterator[tuple[list[OpenAlexRecord], str | None, int | None]]:
        """Every page of the selection, following the cursor.

        Cursor paging rather than offsets. OpenAlex caps `page` at 10,000 results, and a
        harvest is measured in hundreds of thousands — the cursor is the only way through a
        selection larger than that, and it is also cheaper for the server, which is a
        reasonable thing to care about when using a free service heavily.
        """
        cursor = resume_from or "*"

        while cursor:
            params: dict[str, str] = {
                "per-page": str(PAGE_SIZE),
                "cursor": cursor,
                "select": SELECT_FIELDS,
            }
            if filters:
                params["filter"] = filters
            if query:
                params["search"] = query
            if self._mailto:
                # The "polite pool": OpenAlex gives identified clients a faster, more reliable
                # queue. Free services stay free partly because heavy users identify themselves.
                params["mailto"] = self._mailto

            body = await self._get(params)

            works = body.get("results") or []
            records = [record for work in works if (record := parse_work(work)) is not None]

            meta = body.get("meta") or {}
            next_cursor = meta.get("next_cursor")
            total = meta.get("count")

            yield records, next_cursor, total if isinstance(total, int) else None

            # An empty page with a cursor still pointing forward would loop for ever.
            if not works or not next_cursor:
                return
            cursor = next_cursor
            await asyncio.sleep(self._min_delay)


def _retry_after(response: httpx.Response) -> float | None:
    """The `Retry-After` header, when it is a number of seconds worth waiting."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return max(0.0, min(seconds, MAXIMUM_BACKOFF_SECONDS))


def _row(record: OpenAlexRecord) -> dict[str, object]:
    return {
        "source": CatalogSource.openalex,
        "external_id": record.external_id,
        "doi": record.doi[:255] if record.doi else None,
        "title": record.title,
        "abstract": record.abstract,
        "authors": record.authors or [],
        "categories": record.topics or [],
        # Truncated to the column width, and the first topic only: OpenAlex topic names are
        # full phrases rather than the short codes arXiv uses, so some exceed 32 characters.
        "primary_category": (record.topics[0][:32] if record.topics else None),
        "journal_ref": record.journal_ref,
        "comments": None,
        "published_on": record.published_on,
        "updated_on": None,
        "pdf_url": record.pdf_url,
        "landing_url": record.landing_url,
    }


async def store_works(db: AsyncSession, records: Sequence[OpenAlexRecord]) -> tuple[int, int]:
    """Write a batch, returning how many were new and how many were corrections."""
    if not records:
        return (0, 0)

    # Collapsed first: one statement may not touch the same key twice, and a filtered
    # selection can return the same work under two topics.
    unique = {record.external_id: _row(record) for record in records}
    ids = list(unique)

    existing = set(
        (
            await db.execute(
                select(CatalogPaper.external_id).where(
                    CatalogPaper.source == CatalogSource.openalex,
                    CatalogPaper.external_id.in_(ids),
                )
            )
        )
        .scalars()
        .all()
    )

    statement = insert(CatalogPaper).values(list(unique.values()))
    statement = statement.on_conflict_do_update(
        index_elements=[CatalogPaper.source, CatalogPaper.external_id],
        set_={
            column: statement.excluded[column]
            for column in (
                "doi",
                "title",
                "abstract",
                "authors",
                "categories",
                "primary_category",
                "journal_ref",
                "published_on",
                "pdf_url",
                "landing_url",
            )
        },
    )
    await db.execute(statement)
    await db.commit()

    updated = len(existing)
    return (len(ids) - updated, updated)


async def count_openalex(db: AsyncSession) -> int:
    return int(
        await db.scalar(
            select(func.count())
            .select_from(CatalogPaper)
            .where(CatalogPaper.source == CatalogSource.openalex)
        )
        or 0
    )


__all__ = [
    "HarvestProgress",
    "OpenAlexHarvester",
    "OpenAlexRecord",
    "count_openalex",
    "parse_work",
    "store_works",
]
