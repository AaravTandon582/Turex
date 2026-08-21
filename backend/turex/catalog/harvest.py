"""Pulling arXiv's metadata into the catalog.

A harvest is a long-running loop over a paginated feed, so the interesting decisions are all
about what happens when it goes wrong two hours in.

**Flow control is the endpoint's to set, not ours.** arXiv answers `503` with a `Retry-After`
header when it wants a pause, and that is a normal part of the protocol here rather than a
failure — a harvest that treats it as an error stops on the first busy minute. It is obeyed
exactly, and requests are spaced by a floor delay besides, because hammering a free public
service is how access gets withdrawn for everybody.

**Progress is durable.** Each page is committed as it arrives, so a run killed at page 800
keeps 800 pages of work. The resumption token is printed on exit and accepted on the next run,
so the harvest continues rather than restarting.

**Writes are idempotent**, which is what makes resuming safe even when a token rewinds. Every
page is one `INSERT … ON CONFLICT DO UPDATE` on the arXiv id, so re-harvesting an overlapping
range corrects the existing rows instead of failing on a unique violation or duplicating them.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import date

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from turex.catalog.records import CatalogRecord, HarvestError, RecordPage, parse_page
from turex.core.logging import get_logger
from turex.models.catalog import CatalogPaper, CatalogSource

logger = get_logger(__name__)

OAI_ENDPOINT = "https://export.arxiv.org/oai2"

MINIMUM_DELAY_SECONDS = 3.0
"""arXiv's published guidance for automated access. A floor, not a target."""

MAXIMUM_BACKOFF_SECONDS = 300.0
"""A cap on what a `Retry-After` header can ask for.

Without one, a misconfigured or hostile response can park the harvest for a day. Five minutes
is longer than any real backoff arXiv sends and short enough to notice.
"""

MAX_RESPONSE_BYTES = 64 * 1024 * 1024
"""A page is normally under 4MB. This is a bound on memory, not a limit anyone should reach."""

TRANSIENT_STATUSES = frozenset({500, 502, 503, 504})

ARXIV_SETS: tuple[str, ...] = (
    "cs",
    "math",
    "physics",
    "q-bio",
    "q-fin",
    "stat",
    "eess",
    "econ",
)
"""Every top-level archive arXiv publishes, read from its own `ListSets` response.

Harvesting these in turn covers the whole corpus, and covers it *resumably* — a run with no
set at all is one indivisible feed of 2.6 million records, so a token that expires two thirds
of the way through has nowhere to restart from except the beginning. Per-set runs bound the
loss to whichever archive was in flight.

Ordered smallest-interest-last is deliberate: computer science first means the catalog is
useful within the first twenty minutes rather than only when the whole thing finishes.
"""

MINIMUM_FREE_BYTES = 2 * 1024 * 1024 * 1024
"""Stop harvesting when the disk has less than this free.

Two gigabytes is not a lot of headroom, but the alternative to *some* threshold is filling the
disk, at which point PostgreSQL stops accepting writes and so does everything else on the
machine. A harvest is the one thing here that grows without bound, so it is the one thing that
should notice. It stops cleanly and leaves a resumption token, which makes it recoverable
rather than a wedge.
"""


def free_bytes(path: str = ".") -> int:
    """Free space on the filesystem holding `path`.

    The database's filesystem is what actually matters and may differ from this one. Checking
    where the process runs is the approximation available without asking PostgreSQL where it
    keeps its data directory, and on every deployment Turex has it is the same disk.
    """
    stats = os.statvfs(path)
    return stats.f_bavail * stats.f_frsize


class DiskFullError(RuntimeError):
    """The harvest stopped because there is no room left, not because the feed ended."""


@dataclass(slots=True)
class HarvestProgress:
    """Running totals, updated in place so a caller can report as it goes."""

    pages: int = 0
    records: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    estimated_total: int | None = None
    resumption_token: str | None = None


class ArxivHarvester:
    """Reads pages from the OAI-PMH feed, respecting the endpoint's pacing."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        endpoint: str = OAI_ENDPOINT,
        min_delay: float = MINIMUM_DELAY_SECONDS,
        max_attempts: int = 12,
    ) -> None:
        self._client = client
        self._endpoint = endpoint
        self._min_delay = min_delay
        self._max_attempts = max_attempts

    async def _get(self, params: dict[str, str]) -> bytes:
        """One request, retrying only what is worth retrying.

        Twelve attempts rather than a handful. Backing off from three seconds, six attempts is
        about a minute and a half of patience — fine for a short run and not nearly enough for
        one that lasts eleven hours, where arXiv throttling a heavy client is a normal event
        rather than an outage. Measured: a full harvest died on a `ReadTimeout` after ninety
        seconds of trying, having already fetched 390,000 records successfully.

        A `503` here is flow control rather than an outage, so it waits for the interval the
        header names and does not count against a shorter budget. A `4xx` is a bad request —
        an expired resumption token, an unknown set — and retrying it just repeats the mistake,
        so it raises immediately with the body, which is where OAI-PMH puts the reason.
        """
        delay = self._min_delay
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get(self._endpoint, params=params)
            except httpx.HTTPError as exc:
                if attempt == self._max_attempts:
                    raise HarvestError(
                        f"the request failed after {attempt} attempts: {_describe(exc)}"
                    ) from exc
                logger.warning(
                    "harvest request failed, retrying",
                    extra={"attempt": attempt, "error": _describe(exc)},
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAXIMUM_BACKOFF_SECONDS)
                continue

            if response.status_code in TRANSIENT_STATUSES:
                wait = _retry_after(response) or delay
                if attempt == self._max_attempts:
                    raise HarvestError(
                        f"the endpoint stayed unavailable after {attempt} attempts "
                        f"(HTTP {response.status_code})"
                    )
                logger.info(
                    "the endpoint asked us to wait",
                    extra={"seconds": wait, "status": response.status_code},
                )
                await asyncio.sleep(wait)
                delay = min(delay * 2, MAXIMUM_BACKOFF_SECONDS)
                continue

            if response.status_code >= 400:
                raise HarvestError(f"HTTP {response.status_code}: {response.text[:400].strip()}")

            if len(response.content) > MAX_RESPONSE_BYTES:
                raise HarvestError(
                    f"the response was {len(response.content)} bytes, over the "
                    f"{MAX_RESPONSE_BYTES} byte limit"
                )
            return response.content

        raise HarvestError("ran out of attempts")

    async def pages(
        self,
        *,
        set_spec: str | None = None,
        since: date | None = None,
        until: date | None = None,
        resume_from: str | None = None,
    ) -> AsyncIterator[RecordPage]:
        """Every page of the selection, in order, pausing between requests.

        A resumption token stands alone: the OAI-PMH spec forbids sending it alongside the
        original selection arguments, and arXiv enforces that with `badArgument`. So the first
        request carries the filters and every later one carries only the token.
        """
        params: dict[str, str]
        if resume_from:
            params = {"verb": "ListRecords", "resumptionToken": resume_from}
        else:
            params = {"verb": "ListRecords", "metadataPrefix": "arXiv"}
            if set_spec:
                params["set"] = set_spec
            if since:
                params["from"] = since.isoformat()
            if until:
                params["until"] = until.isoformat()

        first = True
        while True:
            if not first:
                # Spaced before the request, not after the last one, so the pause is skipped
                # entirely when the harvest is about to stop.
                await asyncio.sleep(self._min_delay)
            first = False

            page = parse_page(await self._get(params))
            yield page

            if not page.resumption_token:
                return
            params = {"verb": "ListRecords", "resumptionToken": page.resumption_token}


def _describe(exc: Exception) -> str:
    """An exception as a line someone can act on.

    Several httpx errors carry an empty message — `ReadError` and `ConnectError` most often —
    so interpolating `str(exc)` produced "the harvest stopped: " with nothing after it. That
    happened for real, two hours and 192,000 papers into a run, and left no way to tell a
    dropped connection from a DNS failure. The class name is the part that distinguishes them.
    """
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _retry_after(response: httpx.Response) -> float | None:
    """The `Retry-After` header, if it is a number of seconds we are willing to wait."""
    raw = response.headers.get("retry-after")
    if not raw:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        # The header may also carry an HTTP date. arXiv sends seconds; a date form falls back
        # to the caller's own backoff rather than growing a date parser for a case that has
        # never been observed from this endpoint.
        return None
    return max(0.0, min(seconds, MAXIMUM_BACKOFF_SECONDS))


def _row(record: CatalogRecord) -> dict[str, object]:
    return {
        "source": CatalogSource.arxiv,
        "external_id": record.arxiv_id,
        # Stored rather than derived. For arXiv these are a pure function of the id, but the
        # catalog also holds sources where they are not, and a column that is sometimes
        # derived and sometimes stored is a column nobody can reason about.
        "pdf_url": f"https://arxiv.org/pdf/{record.arxiv_id}",
        "landing_url": f"https://arxiv.org/abs/{record.arxiv_id}",
        "doi": record.doi[:255] if record.doi else None,
        "title": record.title,
        "abstract": record.abstract,
        "authors": record.authors,
        "categories": record.categories,
        "primary_category": record.primary_category[:32] if record.primary_category else None,
        "journal_ref": record.journal_ref,
        "comments": record.comments,
        "published_on": record.published_on,
        "updated_on": record.updated_on,
    }


async def store_records(db: AsyncSession, records: Sequence[CatalogRecord]) -> tuple[int, int]:
    """Write a batch, returning how many rows were new and how many were corrections.

    Two statements for the whole batch, not two per record. A per-record `SELECT` then
    `INSERT` would be two round trips per paper — at a thousand papers a page and hundreds of
    pages, that is the difference between a harvest that finishes in minutes and one that
    finishes in hours.

    The first statement asks which of these ids already exist, purely so the run can report
    "new" separately from "corrected". `xmax = 0` would get the same answer inside the upsert
    and save a round trip, but it reads a system column whose behaviour around subtransactions
    is not something worth depending on for a progress counter.

    **Duplicates within the batch are collapsed first.** PostgreSQL raises `ON CONFLICT DO
    UPDATE command cannot affect row a second time` when one statement touches the same key
    twice, and arXiv does send a paper twice in a single page when it belongs to two of the
    requested sets. The last occurrence wins, since later records carry the newer metadata.
    """
    if not records:
        return (0, 0)

    unique: dict[str, dict[str, object]] = {record.arxiv_id: _row(record) for record in records}
    ids = list(unique)

    existing = set(
        (
            await db.execute(
                select(CatalogPaper.external_id).where(
                    CatalogPaper.source == CatalogSource.arxiv,
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
                "pdf_url",
                "landing_url",
                "title",
                "abstract",
                "authors",
                "categories",
                "primary_category",
                "journal_ref",
                "comments",
                "published_on",
                "updated_on",
            )
        },
    )
    await db.execute(statement)
    await db.commit()

    updated = len(existing)
    return (len(ids) - updated, updated)


ANALYZE_EVERY_PAGES = 50
"""How often a running harvest refreshes the planner's statistics.

Fifty pages is roughly 65,000 papers, and `ANALYZE` on a table that size takes about two
seconds — nothing against the twenty minutes those pages take to arrive.

This is not housekeeping; it is the difference between search working and not. Autovacuum's
threshold is proportional to the table's *existing* size, so a table that grows from five
thousand rows to two hundred thousand keeps statistics describing the five thousand for a long
while. With those, PostgreSQL mis-estimates how many rows a common word matches and abandons
the GIN index for a sequential scan: measured, the broadest query on this corpus took 1.5
seconds on stale statistics and 175ms on fresh ones, for the same rows and the same index.
"""


async def analyze_catalog(db: AsyncSession) -> None:
    """Refresh the planner's statistics for the catalog table.

    Committed first because `ANALYZE` cannot see rows this session has not written out yet,
    and statistics gathered without the batch that just landed are the ones being replaced.
    """
    await db.commit()
    await db.execute(text("ANALYZE catalog_papers"))
    await db.commit()


async def count_catalog(db: AsyncSession) -> int:
    """How many papers the catalog holds."""
    return int((await db.execute(select(func.count()).select_from(CatalogPaper))).scalar_one())


async def harvest(
    db: AsyncSession,
    harvester: ArxivHarvester,
    *,
    set_spec: str | None = None,
    since: date | None = None,
    until: date | None = None,
    resume_from: str | None = None,
    max_records: int | None = None,
    on_page: Callable[[HarvestProgress], None] | None = None,
) -> HarvestProgress:
    """Run a harvest to completion, or until `max_records` papers have been stored.

    Progress is committed per page, so stopping at any point — a limit, a keyboard interrupt,
    a crash — keeps everything harvested so far. `progress.resumption_token` holds the token
    that continues from where it stopped, which is what makes a multi-hour harvest restartable
    rather than all-or-nothing.
    """
    progress = HarvestProgress()

    async for page in harvester.pages(
        set_spec=set_spec, since=since, until=until, resume_from=resume_from
    ):
        inserted, updated = await store_records(db, page.records)

        progress.pages += 1
        progress.records += len(page.records)
        progress.inserted += inserted
        progress.updated += updated
        progress.skipped += page.skipped
        progress.resumption_token = page.resumption_token
        if page.complete_size is not None:
            progress.estimated_total = page.complete_size

        if on_page is not None:
            on_page(progress)

        if progress.pages % ANALYZE_EVERY_PAGES == 0:
            await analyze_catalog(db)

        # Checked per page rather than per record: a page is about 4MB of rows, so the disk
        # cannot cross the threshold and fill within one, and a `statvfs` per record would be
        # a syscall per paper for no benefit.
        if free_bytes() < MINIMUM_FREE_BYTES:
            await analyze_catalog(db)
            raise DiskFullError(
                f"stopping with {free_bytes() / 1_000_000_000:.1f}GB free — "
                f"below the {MINIMUM_FREE_BYTES / 1_000_000_000:.0f}GB floor"
            )

        if max_records is not None and progress.records >= max_records:
            logger.info(
                "harvest reached its record limit",
                extra={"records": progress.records, "limit": max_records},
            )
            await analyze_catalog(db)
            return progress

    await analyze_catalog(db)

    # The feed ended, so there is nothing left to resume from. Clearing this is what lets a
    # caller tell "finished" from "stopped early", which is the difference between reporting a
    # complete harvest and offering a token to continue with.
    progress.resumption_token = None
    return progress
