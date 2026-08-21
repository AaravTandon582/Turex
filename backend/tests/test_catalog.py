"""The catalog: parsing arXiv's feed, storing it, searching it, and importing from it.

Three groups, in the order a paper travels through them. The parsing tests use saved XML so
they never touch the network; the search and import tests run against the real database,
because every catalog bug found while building this was in SQL that type-checked perfectly —
an ordering clause that rendered `NULLS LAST DESC`, a bounded count whose inner query returned
the count and so was limited to one row, and a date bound sent as a string that PostgreSQL
would not compare against a `date`. None of those are visible without a database.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient, MockTransport, ReadError, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.catalog.harvest import (
    MAX_RESPONSE_BYTES,
    MAXIMUM_BACKOFF_SECONDS,
    ArxivHarvester,
    _retry_after,
    count_catalog,
    harvest,
    store_records,
)
from atlas.catalog.records import (
    CatalogRecord,
    HarvestError,
    normalise_arxiv_id,
    parse_page,
)
from atlas.catalog.service import COUNT_CEILING, CatalogService
from atlas.models.catalog import CatalogPaper


def _envelope(body: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
  <responseDate>2026-08-20T09:00:00Z</responseDate>
  <ListRecords>{body}</ListRecords>
</OAI-PMH>"""


def _record(
    identifier: str = "2103.14030",
    title: str = "Swin Transformer",
    abstract: str = "We present a hierarchical vision transformer.",
    extra: str = "",
) -> str:
    return f"""
    <record>
      <header><identifier>oai:arXiv.org:{identifier}</identifier></header>
      <metadata>
        <arXiv xmlns="http://arxiv.org/OAI/arXiv/">
          <id>{identifier}</id>
          <created>2021-03-25</created>
          <updated>2021-08-17</updated>
          <authors>
            <author><keyname>Liu</keyname><forenames>Ze</forenames></author>
            <author><keyname>Lin</keyname><forenames>Yutong</forenames></author>
          </authors>
          <title>{title}</title>
          <categories>cs.CV cs.LG</categories>
          <abstract>{abstract}</abstract>
          {extra}
        </arXiv>
      </metadata>
    </record>"""


class TestParsing:
    def test_a_record_becomes_a_catalog_entry(self) -> None:
        page = parse_page(_envelope(_record()))
        [paper] = page.records

        assert paper.arxiv_id == "2103.14030"
        assert paper.title == "Swin Transformer"
        assert paper.categories == ["cs.CV", "cs.LG"]
        assert paper.primary_category == "cs.CV"
        assert paper.published_on == date(2021, 3, 25)
        assert paper.updated_on == date(2021, 8, 17)

    def test_author_names_are_joined_in_the_papers_own_order(self) -> None:
        [paper] = parse_page(_envelope(_record())).records
        assert [author["name"] for author in paper.authors] == ["Ze Liu", "Yutong Lin"]

    def test_an_author_with_only_a_surname_keeps_it(self) -> None:
        """Collaboration names and mononyms have no forenames, and must not gain a space."""
        body = _record().replace(
            "<author><keyname>Liu</keyname><forenames>Ze</forenames></author>",
            "<author><keyname>ATLAS Collaboration</keyname></author>",
        )
        [paper] = parse_page(_envelope(body)).records
        assert paper.authors[0] == {"name": "ATLAS Collaboration"}

    def test_a_wrapped_abstract_is_collapsed_to_one_line(self) -> None:
        """arXiv wraps abstracts inside the XML. Stored raw they render as ragged nonsense."""
        body = _record(abstract="  We present\n      a hierarchical\n   vision transformer.  ")
        [paper] = parse_page(_envelope(body)).records
        assert paper.abstract == "We present a hierarchical vision transformer."

    def test_a_deleted_record_is_skipped_rather_than_stored(self) -> None:
        """Withdrawn papers arrive as tombstones. They are a normal part of the feed."""
        body = """
        <record>
          <header status="deleted"><identifier>oai:arXiv.org:cs/0000001</identifier></header>
        </record>"""
        page = parse_page(_envelope(body + _record()))
        assert [paper.arxiv_id for paper in page.records] == ["2103.14030"]
        assert page.skipped == 1

    def test_one_bad_record_does_not_discard_the_good_ones_beside_it(self) -> None:
        broken = """
        <record>
          <header><identifier>oai:arXiv.org:bad</identifier></header>
          <metadata><arXiv xmlns="http://arxiv.org/OAI/arXiv/"><id>bad</id></arXiv></metadata>
        </record>"""
        page = parse_page(_envelope(broken + _record()))
        assert len(page.records) == 1
        assert page.skipped == 1

    def test_the_resumption_token_and_size_are_read(self) -> None:
        body = _record() + (
            '<resumptionToken completeListSize="2600000">skip=1300</resumptionToken>'
        )
        page = parse_page(_envelope(body))
        assert page.resumption_token == "skip=1300"
        assert page.complete_size == 2_600_000

    def test_the_last_page_has_no_token(self) -> None:
        assert parse_page(_envelope(_record())).resumption_token is None

    def test_an_oai_error_stops_the_harvest(self) -> None:
        """`badResumptionToken` must not look like an empty page and end the run quietly."""
        body = """<?xml version="1.0"?>
        <OAI-PMH xmlns="http://www.openarchives.org/OAI/2.0/">
          <error code="badResumptionToken">expired</error>
        </OAI-PMH>"""
        with pytest.raises(HarvestError, match="badResumptionToken"):
            parse_page(body)

    def test_a_document_type_declaration_is_refused(self) -> None:
        """Every entity-expansion attack needs a DTD, and OAI-PMH never sends one."""
        bomb = (
            '<?xml version="1.0"?>\n'
            '<!DOCTYPE lolz [<!ENTITY lol "lol">'
            '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>\n'
            "<OAI-PMH><x>&lol2;</x></OAI-PMH>"
        )
        with pytest.raises(HarvestError, match="document type"):
            parse_page(bomb)

    def test_malformed_xml_raises_rather_than_returning_nothing(self) -> None:
        with pytest.raises(HarvestError, match="valid XML"):
            parse_page("<OAI-PMH><unclosed>")

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("oai:arXiv.org:2103.14030v2", "2103.14030"),
            ("2103.14030", "2103.14030"),
            ("oai:arXiv.org:cs/0508010", "cs/0508010"),
            ("cs/0508010v1", "cs/0508010"),
        ],
    )
    def test_identifiers_are_reduced_to_a_bare_versionless_id(
        self, raw: str, expected: str
    ) -> None:
        """One row per paper, not per version — and the version-less PDF URL is the newest."""
        assert normalise_arxiv_id(raw) == expected


class TestStoring:
    async def test_records_are_written_and_counted(self, db: AsyncSession) -> None:
        inserted, updated = await store_records(
            db, [CatalogRecord(arxiv_id="1", title="One"), CatalogRecord(arxiv_id="2", title="Two")]
        )
        assert (inserted, updated) == (2, 0)

    async def test_re_harvesting_corrects_a_row_rather_than_duplicating_it(
        self, db: AsyncSession
    ) -> None:
        """arXiv re-sends any paper whose metadata changed, so overlap is the normal case."""
        await store_records(db, [CatalogRecord(arxiv_id="1", title="Old title")])
        inserted, updated = await store_records(
            db, [CatalogRecord(arxiv_id="1", title="Corrected title")]
        )

        assert (inserted, updated) == (0, 1)
        stored = (await db.execute(_by_id("1"))).scalar_one()
        assert stored.title == "Corrected title"

    async def test_a_paper_repeated_within_one_batch_does_not_fail(self, db: AsyncSession) -> None:
        """PostgreSQL refuses to let one statement touch the same key twice, and arXiv sends a
        paper twice in a page when it belongs to two of the requested sets."""
        inserted, _ = await store_records(
            db,
            [
                CatalogRecord(arxiv_id="1", title="First occurrence"),
                CatalogRecord(arxiv_id="1", title="Second occurrence"),
            ],
        )
        assert inserted == 1
        stored = (await db.execute(_by_id("1"))).scalar_one()
        assert stored.title == "Second occurrence", "the later record carries newer metadata"

    async def test_an_empty_batch_is_not_a_statement(self, db: AsyncSession) -> None:
        assert await store_records(db, []) == (0, 0)

    async def test_the_search_vector_is_filled_without_anyone_writing_it(
        self, db: AsyncSession
    ) -> None:
        """The trigger is the whole guarantee that the index cannot go stale."""
        await store_records(
            db, [CatalogRecord(arxiv_id="1", title="Diffusion", abstract="Denoising steps.")]
        )
        stored = (await db.execute(_by_id("1"))).scalar_one()
        assert stored.search_tsv is not None

        await store_records(db, [CatalogRecord(arxiv_id="1", title="Retrieval augmentation")])
        found = await CatalogService(db).search(query="retrieval")
        assert [paper.arxiv_id for paper in found.items] == ["1"]


class TestSearch:
    @pytest.fixture(autouse=True)
    async def corpus(self, db: AsyncSession) -> None:
        await store_records(
            db,
            [
                CatalogRecord(
                    arxiv_id="a",
                    title="Attention Is All You Need",
                    abstract="We propose the Transformer, based solely on attention.",
                    categories=["cs.CL", "cs.LG"],
                    published_on=date(2017, 6, 12),
                ),
                CatalogRecord(
                    arxiv_id="b",
                    title="Deep Residual Learning",
                    abstract="Residual connections ease the training of deep networks.",
                    categories=["cs.CV"],
                    published_on=date(2015, 12, 10),
                ),
                CatalogRecord(
                    arxiv_id="c",
                    title="A Survey of Graph Methods",
                    abstract="A survey. It mentions attention once, in passing.",
                    categories=["cs.LG"],
                    published_on=date(2021, 1, 5),
                ),
            ],
        )

    async def test_a_title_match_outranks_a_passing_mention(self, db: AsyncSession) -> None:
        """The whole point of weighting the title above the abstract."""
        found = await CatalogService(db).search(query="attention")
        assert found.items[0].arxiv_id == "a"

    async def test_a_query_matching_nothing_returns_nothing(self, db: AsyncSession) -> None:
        found = await CatalogService(db).search(query="thermodynamics")
        assert found.items == []
        assert found.total == 0

    @pytest.mark.parametrize(
        "hostile",
        [
            "foo &",
            '"unbalanced',
            "a | | b",
            "'; DROP TABLE catalog_papers; --",
            "<script>alert(1)</script>",
            "!!!",
            ")" * 50,
        ],
    )
    async def test_a_malformed_query_is_answered_rather_than_raising(
        self, db: AsyncSession, hostile: str
    ) -> None:
        """`to_tsquery` treats its argument as an expression and rejects a stray operator with
        a syntax error — from a search box, that is a 500 on a trailing ampersand."""
        found = await CatalogService(db).search(query=hostile)
        assert isinstance(found.total, int)

        assert (await db.execute(_by_id("a"))).scalar_one_or_none() is not None

    async def test_a_category_filter_finds_cross_listed_papers(self, db: AsyncSession) -> None:
        """A paper cross-listed into cs.LG belongs there as far as a reader is concerned."""
        found = await CatalogService(db).search(category="cs.LG")
        assert {paper.arxiv_id for paper in found.items} == {"a", "c"}

    async def test_year_bounds_are_inclusive_at_both_ends(self, db: AsyncSession) -> None:
        """Sent as dates, not ISO strings: asyncpg binds by Python type, and PostgreSQL has no
        `date >= character varying` operator."""
        found = await CatalogService(db).search(year_from=2015, year_to=2017)
        assert {paper.arxiv_id for paper in found.items} == {"a", "b"}

    async def test_no_query_browses_the_newest_first(self, db: AsyncSession) -> None:
        found = await CatalogService(db).search()
        assert [paper.arxiv_id for paper in found.items] == ["c", "a", "b"]

    async def test_newest_sort_overrides_relevance(self, db: AsyncSession) -> None:
        found = await CatalogService(db).search(query="attention", sort="newest")
        assert [paper.arxiv_id for paper in found.items] == ["c", "a"]

    async def test_paging_does_not_repeat_or_skip_a_paper(self, db: AsyncSession) -> None:
        """Without a total order, equal-ranked rows swap between pages — which shows one paper
        twice and hides another entirely."""
        service = CatalogService(db)
        first = await service.search(limit=2, offset=0)
        second = await service.search(limit=2, offset=2)

        seen = [paper.arxiv_id for paper in first.items] + [
            paper.arxiv_id for paper in second.items
        ]
        assert sorted(seen) == ["a", "b", "c"]

    async def test_a_small_result_set_is_counted_exactly(self, db: AsyncSession) -> None:
        found = await CatalogService(db).search(query="attention")
        assert found.total == 2
        assert found.total_is_exact is True

    async def test_the_count_stops_at_its_ceiling_and_says_so(self, db: AsyncSession) -> None:
        """A count over a text search is proportional to how many rows *match*, and a common
        word in a large catalog matches a great many."""
        await store_records(
            db,
            [
                CatalogRecord(arxiv_id=f"bulk-{index}", title="Padding paper about attention")
                for index in range(COUNT_CEILING + 20)
            ],
        )
        found = await CatalogService(db).search(query="attention")
        assert found.total == COUNT_CEILING
        assert found.total_is_exact is False

    async def test_stats_summarise_the_catalog(self, db: AsyncSession) -> None:
        summary = await CatalogService(db).stats()
        assert summary.total == 3
        assert summary.with_abstract == 3
        assert (summary.earliest_year, summary.latest_year) == (2015, 2021)
        assert {entry.category: entry.count for entry in summary.top_categories} == {
            "cs.LG": 2,
            "cs.CL": 1,
            "cs.CV": 1,
        }


class TestRoutes:
    @pytest.fixture(autouse=True)
    async def corpus(self, db: AsyncSession) -> None:
        await store_records(
            db,
            [
                CatalogRecord(
                    arxiv_id="2017.0001",
                    title="Attention Is All You Need",
                    abstract="We propose the Transformer.",
                    categories=["cs.CL"],
                    published_on=date(2017, 6, 12),
                )
            ],
        )

    async def test_search_returns_results_a_page_can_render(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/catalog/search", params={"q": "attention"})
        assert response.status_code == 200

        body = response.json()
        assert body["total"] == 1
        assert body["total_is_exact"] is True

        [paper] = body["items"]
        assert paper["title"] == "Attention Is All You Need"
        assert paper["abs_url"] == "https://arxiv.org/abs/2017.0001"
        assert paper["pdf_url"] == "https://arxiv.org/pdf/2017.0001"
        assert paper["in_library"] is False

    async def test_an_unknown_catalog_paper_is_a_404_not_a_500(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.get(f"{api}/catalog/{uuid.uuid4()}")
        assert response.status_code == 404

    async def test_importing_something_that_is_not_there_is_a_404(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.post(f"{api}/catalog/{uuid.uuid4()}/import")
        assert response.status_code == 404

    async def test_stats_are_reported(self, registered_client: AsyncClient, api: str) -> None:
        response = await registered_client.get(f"{api}/catalog/stats")
        assert response.status_code == 200
        assert response.json()["total"] == 1

    async def test_deep_pagination_is_refused_rather_than_served_slowly(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Page five hundred costs five hundred pages of scanning, and nobody reaches it by
        reading."""
        response = await registered_client.get(f"{api}/catalog/search", params={"offset": 10_001})
        assert response.status_code == 422

    async def test_the_catalog_is_shared_but_in_library_is_not(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        """The one table in the schema that is not owner-scoped, so this is worth stating.

        Both accounts see the same paper — the metadata is public. What must never leak is
        whether the *other* account has imported it, since that is a fact about a person's
        library rather than about the paper.
        """
        entry = (await db.execute(_by_id("2017.0001"))).scalar_one()

        mine = await registered_client.get(f"{api}/catalog/{entry.id}")
        theirs = await other_client.get(f"{api}/catalog/{entry.id}")

        assert mine.status_code == theirs.status_code == 200
        assert mine.json()["title"] == theirs.json()["title"]
        assert mine.json()["in_library"] is False
        assert theirs.json()["in_library"] is False


def _by_id(arxiv_id: str):  # type: ignore[no-untyped-def]
    from sqlalchemy import select

    return select(CatalogPaper).where(CatalogPaper.arxiv_id == arxiv_id)


class TestFetching:
    """The harvester's HTTP behaviour, against a transport that answers from a script.

    None of this touches the network. What is being tested is how a run *survives* a feed that
    misbehaves — the 503s arXiv sends as flow control, a dropped connection an hour in, a token
    that has expired — and those are impossible to provoke on demand from the real endpoint.
    """

    @staticmethod
    def _harvester(handler, **kwargs):  # type: ignore[no-untyped-def]
        client = AsyncClient(transport=MockTransport(handler), base_url="https://arxiv.test")
        return ArxivHarvester(client, endpoint="https://arxiv.test/oai2", min_delay=0.0, **kwargs)

    async def test_pages_follow_the_resumption_token_to_the_end(self) -> None:
        seen: list[str] = []

        def handler(request: Request) -> Response:
            token = request.url.params.get("resumptionToken")
            seen.append(token or "first")
            body = _record(identifier=f"page/{len(seen)}")
            if len(seen) < 3:
                body += f"<resumptionToken>skip={len(seen) * 1300}</resumptionToken>"
            return Response(200, text=_envelope(body))

        pages = [page async for page in self._harvester(handler).pages(set_spec="cs")]

        assert len(pages) == 3
        assert seen == ["first", "skip=1300", "skip=2600"]

    async def test_the_first_request_carries_the_filters_and_later_ones_only_the_token(
        self,
    ) -> None:
        """OAI-PMH forbids sending both, and arXiv answers `badArgument` if you do."""
        captured: list[dict[str, str]] = []

        def handler(request: Request) -> Response:
            captured.append(dict(request.url.params))
            body = _record()
            if len(captured) == 1:
                body += "<resumptionToken>more</resumptionToken>"
            return Response(200, text=_envelope(body))

        harvester = self._harvester(handler)
        [_ async for _ in harvester.pages(set_spec="cs", since=date(2024, 1, 1))]

        assert captured[0]["set"] == "cs"
        assert captured[0]["from"] == "2024-01-01"
        assert captured[0]["metadataPrefix"] == "arXiv"

        assert captured[1] == {"verb": "ListRecords", "resumptionToken": "more"}

    async def test_a_503_is_flow_control_and_is_waited_out(self) -> None:
        """arXiv answers 503 with `Retry-After` when it wants a pause. A harvest that treats
        that as an outage stops on the first busy minute."""
        attempts = 0

        def handler(request: Request) -> Response:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                return Response(503, headers={"Retry-After": "0"})
            return Response(200, text=_envelope(_record()))

        pages = [page async for page in self._harvester(handler).pages()]

        assert attempts == 3
        assert len(pages[0].records) == 1

    async def test_an_absurd_retry_after_is_capped(self) -> None:
        """Without a cap, one bad header parks the harvest for a day."""
        assert _retry_after(Response(503, headers={"Retry-After": "999999"})) == (
            MAXIMUM_BACKOFF_SECONDS
        )

    async def test_a_retry_after_date_falls_back_rather_than_raising(self) -> None:
        header = {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
        assert _retry_after(Response(503, headers=header)) is None

    async def test_a_dropped_connection_is_retried(self) -> None:
        attempts = 0

        def handler(request: Request) -> Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ReadError("")
            return Response(200, text=_envelope(_record()))

        pages = [page async for page in self._harvester(handler).pages()]
        assert attempts == 2
        assert len(pages[0].records) == 1

    async def test_a_failure_that_never_recovers_names_what_went_wrong(self) -> None:
        """An httpx `ReadError` carries an empty message, so interpolating it produced "the
        harvest stopped: " with nothing after it — which happened for real, 192,000 papers
        into a run, and left no way to tell a dropped connection from a DNS failure."""

        def handler(request: Request) -> Response:
            raise ReadError("")

        with pytest.raises(HarvestError, match="ReadError"):
            [_ async for _ in self._harvester(handler, max_attempts=2).pages()]

    async def test_a_client_error_is_not_retried(self) -> None:
        """An expired token or an unknown set is a bad request; retrying repeats the mistake."""
        attempts = 0

        def handler(request: Request) -> Response:
            nonlocal attempts
            attempts += 1
            return Response(400, text="badArgument")

        with pytest.raises(HarvestError, match="400"):
            [_ async for _ in self._harvester(handler).pages()]
        assert attempts == 1

    async def test_an_oversized_response_is_refused_rather_than_parsed(self) -> None:
        def handler(request: Request) -> Response:
            return Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1))

        with pytest.raises(HarvestError, match="over the"):
            [_ async for _ in self._harvester(handler).pages()]

    async def test_a_run_stores_what_it_reads_and_reports_it(self, db: AsyncSession) -> None:
        """The whole loop: pages in, rows out, counted."""

        def handler(request: Request) -> Response:
            token = request.url.params.get("resumptionToken")
            index = 2 if token else 1
            body = _record(identifier=f"run/{index}")
            if index == 1:
                body += '<resumptionToken completeListSize="2">next</resumptionToken>'
            return Response(200, text=_envelope(body))

        progress = await harvest(db, self._harvester(handler))

        assert (progress.pages, progress.records, progress.inserted) == (2, 2, 2)
        assert progress.estimated_total == 2
        assert progress.resumption_token is None, "a finished harvest has nothing to resume"
        assert await count_catalog(db) == 2

    async def test_a_run_stops_at_its_record_limit_and_can_be_resumed(
        self, db: AsyncSession
    ) -> None:
        def handler(request: Request) -> Response:
            skip = request.url.params.get("resumptionToken", "0")
            body = _record(identifier=f"limit/{skip}")
            body += f"<resumptionToken>{skip}x</resumptionToken>"
            return Response(200, text=_envelope(body))

        progress = await harvest(db, self._harvester(handler), max_records=1)

        assert progress.records == 1
        assert progress.resumption_token is not None, "stopping early must leave a way back"
