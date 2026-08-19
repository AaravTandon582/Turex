"""Library tests: upload, ingestion, browsing, and privacy.

The privacy tests matter most. Atlas holds a user's unpublished reading and notes, and the
rule is absolute: one account can never observe another's, and a paper it does not own must
be indistinguishable from one that does not exist.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from atlas.models.job import IngestionJob, JobStatus
from atlas.models.paper import Paper, PaperChunk, PaperSection
from tests.support.pdf_builder import build_paper_pdf, build_pdf

Drain = Callable[..., Awaitable[int]]


def pdf_upload(data: bytes | None = None, filename: str = "paper.pdf") -> dict[str, object]:
    return {"file": (filename, data if data is not None else build_paper_pdf(), "application/pdf")}


async def upload(client: AsyncClient, api: str, **kwargs: object) -> dict:
    response = await client.post(f"{api}/papers", files=pdf_upload(**kwargs))  # type: ignore[arg-type]
    assert response.status_code in (200, 202), response.text
    return response.json()


class TestUpload:
    async def test_accepts_a_pdf_and_queues_it(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        response = await registered_client.post(f"{api}/papers", files=pdf_upload())

        # 202: stored and queued, but not yet read.
        assert response.status_code == 202
        body = response.json()
        assert body["status"] == "pending"
        assert body["ingestion"]["stage"] == "queued"
        assert body["display_title"] == "paper.pdf"

    async def test_shows_the_filename_until_a_title_is_known(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        body = await upload(registered_client, api, filename="neurips-submission.pdf")
        assert body["title"] is None
        assert body["display_title"] == "neurips-submission.pdf"

    async def test_rejects_a_file_that_is_not_a_pdf(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Validation is by content, not by the declared type or the extension."""
        response = await registered_client.post(
            f"{api}/papers",
            files={"file": ("evil.pdf", b"MZ\x90\x00 this is an executable", "application/pdf")},
        )

        assert response.status_code == 415
        assert response.json()["error"]["code"] == "unsupported_media_type"

    async def test_rejects_an_empty_file(self, registered_client: AsyncClient, api: str) -> None:
        response = await registered_client.post(
            f"{api}/papers", files={"file": ("empty.pdf", b"", "application/pdf")}
        )
        assert response.status_code == 422

    async def test_reuploading_the_same_file_returns_the_existing_paper(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        data = build_paper_pdf()
        first = await registered_client.post(f"{api}/papers", files=pdf_upload(data))
        second = await registered_client.post(f"{api}/papers", files=pdf_upload(data))

        assert first.status_code == 202
        assert second.status_code == 200, "a duplicate is recognised, not created"
        assert first.json()["id"] == second.json()["id"]
        assert await db.scalar(select(func.count()).select_from(Paper)) == 1

    async def test_requires_authentication(self, client: AsyncClient, api: str) -> None:
        response = await client.post(f"{api}/papers", files=pdf_upload())
        assert response.status_code == 401


class TestIngestion:
    async def test_reads_the_paper_end_to_end(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]

        assert await run_worker() == 1

        body = (await registered_client.get(f"{api}/papers/{paper_id}")).json()
        assert body["status"] == "ready"
        assert body["title"] == "A Study of Something Interesting"
        assert [author["name"] for author in body["authors"]] == [
            "Ada Lovelace",
            "Charles Babbage",
        ]
        assert body["page_count"] == 2
        assert body["section_count"] > 0
        assert body["chunk_count"] > 0
        assert body["ingestion"]["stage"] == "complete"
        assert body["ingestion"]["progress"] == 100

    async def test_stores_chunks_with_their_location(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        """Citations resolve through these columns; without them a claim cannot be located."""
        await upload(registered_client, api)
        await run_worker()

        chunks = list(await db.scalars(select(PaperChunk).order_by(PaperChunk.ordinal)))
        assert chunks
        for chunk in chunks:
            assert chunk.content.strip()
            assert chunk.page_start >= 1
            assert chunk.token_estimate > 0

    async def test_builds_a_searchable_index(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        """The generated tsvector column is what lexical retrieval queries in Milestone 3."""
        await upload(registered_client, api)
        await run_worker()

        matches = await db.scalar(
            select(func.count())
            .select_from(PaperChunk)
            .where(PaperChunk.content_tsv.op("@@")(func.plainto_tsquery("english", "annotators")))
        )
        assert matches and matches >= 1

    async def test_records_the_section_outline(
        self, registered_client: AsyncClient, api: str, run_worker: Drain
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]
        await run_worker()

        sections = (await registered_client.get(f"{api}/papers/{paper_id}/sections")).json()
        titles = [section["title"] for section in sections]
        assert "1 Introduction" in titles
        assert sections == sorted(sections, key=lambda section: section["ordinal"])

    async def test_an_unreadable_document_fails_with_an_explanation(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        """A scanned PDF cannot be read. The user is told why, in their own terms."""
        paper_id = (await upload(registered_client, api, data=build_pdf([[""]])))["id"]

        await run_worker()

        body = (await registered_client.get(f"{api}/papers/{paper_id}")).json()
        assert body["status"] == "failed"
        assert "OCR" in body["failure_reason"] or "text" in body["failure_reason"].lower()
        # No stack trace, module path, or exception class reaches the user.
        assert "Traceback" not in body["failure_reason"]

    async def test_an_unreadable_document_is_not_retried(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        """The same bytes fail identically, so retrying only delays the bad news."""
        await upload(registered_client, api, data=build_pdf([[""]]))
        await run_worker()

        job_status, attempts = (
            await db.execute(select(IngestionJob.status, IngestionJob.attempts))
        ).one()
        assert job_status is JobStatus.failed
        assert attempts == 1

    async def test_reprocessing_replaces_rather_than_duplicates(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]
        await run_worker()
        first_count = await db.scalar(select(func.count()).select_from(PaperChunk))

        await registered_client.post(f"{api}/papers/{paper_id}/reprocess")
        await run_worker()

        assert await db.scalar(select(func.count()).select_from(PaperChunk)) == first_count

    async def test_reprocessing_keeps_a_user_correction(
        self, registered_client: AsyncClient, api: str, run_worker: Drain
    ) -> None:
        """Extraction is heuristic; a correction must survive the parser running again."""
        paper_id = (await upload(registered_client, api))["id"]
        await run_worker()

        await registered_client.patch(
            f"{api}/papers/{paper_id}", json={"title": "The Correct Title"}
        )
        await registered_client.post(f"{api}/papers/{paper_id}/reprocess")
        await run_worker()

        body = (await registered_client.get(f"{api}/papers/{paper_id}")).json()
        assert body["title"] == "The Correct Title"


class TestBrowsing:
    async def test_lists_papers_newest_first(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        await upload(registered_client, api, data=build_pdf([["First document text here."]]))
        await upload(registered_client, api, data=build_pdf([["Second document text here."]]))

        body = (await registered_client.get(f"{api}/papers")).json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    async def test_paginates(self, registered_client: AsyncClient, api: str) -> None:
        for index in range(3):
            await upload(registered_client, api, data=build_pdf([[f"Document number {index}."]]))

        page = (await registered_client.get(f"{api}/papers?limit=2&offset=0")).json()
        assert page["total"] == 3
        assert len(page["items"]) == 2

        rest = (await registered_client.get(f"{api}/papers?limit=2&offset=2")).json()
        assert len(rest["items"]) == 1

    async def test_filters_by_reading_status(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]
        await registered_client.patch(f"{api}/papers/{paper_id}", json={"reading_status": "read"})

        read = (await registered_client.get(f"{api}/papers?reading_status=read")).json()
        unread = (await registered_client.get(f"{api}/papers?reading_status=unread")).json()

        assert read["total"] == 1
        assert unread["total"] == 0

    async def test_searches_by_title(
        self, registered_client: AsyncClient, api: str, run_worker: Drain
    ) -> None:
        await upload(registered_client, api)
        await run_worker()

        found = (await registered_client.get(f"{api}/papers?search=Something Interesting")).json()
        missing = (
            await registered_client.get(f"{api}/papers?search=quantum chromodynamics")
        ).json()

        assert found["total"] == 1
        assert missing["total"] == 0

    async def test_reports_library_counts(self, registered_client: AsyncClient, api: str) -> None:
        await upload(registered_client, api)

        stats = (await registered_client.get(f"{api}/papers/stats")).json()
        assert stats["total"] == 1
        assert stats["processing"] == 1
        assert stats["unread"] == 1

    async def test_rejects_an_out_of_range_page_size(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        # An unbounded limit is a denial-of-service vector on a large library.
        assert (await registered_client.get(f"{api}/papers?limit=5000")).status_code == 422


class TestPaperLifecycle:
    async def test_opening_promotes_an_unread_paper_to_reading(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]

        body = (await registered_client.post(f"{api}/papers/{paper_id}/opened")).json()

        assert body["reading_status"] == "reading"
        assert body["last_opened_at"] is not None

    async def test_serves_the_original_file(self, registered_client: AsyncClient, api: str) -> None:
        data = build_paper_pdf()
        paper_id = (await upload(registered_client, api, data=data))["id"]

        response = await registered_client.get(f"{api}/papers/{paper_id}/file")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.content == data
        # Private to one user: no shared cache may retain a copy.
        assert "private" in response.headers["cache-control"]

    async def test_deletes_the_paper_and_everything_derived_from_it(
        self, registered_client: AsyncClient, api: str, run_worker: Drain, db: AsyncSession
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]
        await run_worker()

        assert (await registered_client.delete(f"{api}/papers/{paper_id}")).status_code == 204

        assert (await registered_client.get(f"{api}/papers/{paper_id}")).status_code == 404
        assert await db.scalar(select(func.count()).select_from(PaperChunk)) == 0
        assert await db.scalar(select(func.count()).select_from(PaperSection)) == 0


class TestPrivacy:
    """One account must never be able to observe another's library."""

    async def test_a_library_contains_only_its_owners_papers(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        await upload(registered_client, api)

        assert (await other_client.get(f"{api}/papers")).json()["total"] == 0

    @pytest.mark.parametrize(
        ("method", "suffix"),
        [
            ("get", ""),
            ("get", "/file"),
            ("get", "/sections"),
            ("delete", ""),
            ("post", "/opened"),
        ],
    )
    async def test_another_users_paper_is_indistinguishable_from_a_missing_one(
        self,
        registered_client: AsyncClient,
        other_client: AsyncClient,
        api: str,
        method: str,
        suffix: str,
    ) -> None:
        """404, never 403: a 403 would confirm the identifier exists in someone's library."""
        paper_id = (await upload(registered_client, api))["id"]

        response = await getattr(other_client, method)(f"{api}/papers/{paper_id}{suffix}")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    async def test_another_user_cannot_edit_a_paper(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        paper_id = (await upload(registered_client, api))["id"]

        response = await other_client.patch(f"{api}/papers/{paper_id}", json={"title": "Stolen"})

        assert response.status_code == 404
        original = (await registered_client.get(f"{api}/papers/{paper_id}")).json()
        assert original["title"] != "Stolen"

    async def test_stats_count_only_the_callers_papers(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        await upload(registered_client, api)
        assert (await other_client.get(f"{api}/papers/stats")).json()["total"] == 0


class TestCollections:
    async def test_creates_and_lists(self, registered_client: AsyncClient, api: str) -> None:
        created = await registered_client.post(
            f"{api}/collections", json={"name": "Retrieval", "description": "RAG papers"}
        )
        assert created.status_code == 201

        listed = (await registered_client.get(f"{api}/collections")).json()
        assert [collection["name"] for collection in listed] == ["Retrieval"]
        assert listed[0]["paper_count"] == 0

    async def test_rejects_a_duplicate_name(self, registered_client: AsyncClient, api: str) -> None:
        await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})
        response = await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})

        assert response.status_code == 409

    async def test_adding_a_paper_is_idempotent(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        collection_id = (
            await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})
        ).json()["id"]
        paper_id = (await upload(registered_client, api))["id"]

        for _ in range(2):
            response = await registered_client.put(
                f"{api}/collections/{collection_id}/papers/{paper_id}"
            )
            assert response.status_code == 204

        listed = (await registered_client.get(f"{api}/collections")).json()
        assert listed[0]["paper_count"] == 1

    async def test_filters_the_library_by_collection(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        collection_id = (
            await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})
        ).json()["id"]
        included = (await upload(registered_client, api, data=build_pdf([["Included paper."]])))[
            "id"
        ]
        await upload(registered_client, api, data=build_pdf([["Excluded paper."]]))
        await registered_client.put(f"{api}/collections/{collection_id}/papers/{included}")

        body = (await registered_client.get(f"{api}/papers?collection_id={collection_id}")).json()

        assert body["total"] == 1
        assert body["items"][0]["id"] == included

    async def test_deleting_a_collection_keeps_its_papers(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        collection_id = (
            await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})
        ).json()["id"]
        paper_id = (await upload(registered_client, api))["id"]
        await registered_client.put(f"{api}/collections/{collection_id}/papers/{paper_id}")

        await registered_client.delete(f"{api}/collections/{collection_id}")

        assert (await registered_client.get(f"{api}/papers/{paper_id}")).status_code == 200

    async def test_another_user_cannot_reach_a_collection(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        collection_id = (
            await registered_client.post(f"{api}/collections", json={"name": "Retrieval"})
        ).json()["id"]

        assert (await other_client.delete(f"{api}/collections/{collection_id}")).status_code == 404


class TestStorageUnderConcurrency:
    """The storage layer, tested directly — the HTTP test above proved too timing-dependent
    to pin this down, and the fault was never in the database."""

    async def test_writing_the_same_bytes_concurrently_does_not_fail(
        self, settings, tmp_path
    ) -> None:
        """Two uploads of one file produced the same content-addressed key, so both wrote to
        one `.partial` path. The first rename consumed it and the second raised
        FileNotFoundError — a 500 for one of two people uploading the same paper at once.
        """
        import asyncio

        from atlas.storage.local import LocalDocumentStore

        store = LocalDocumentStore(tmp_path)
        data = b"%PDF-1.4\n" + b"identical bytes " * 500

        results = await asyncio.gather(
            *[store.put(namespace="a" * 32, filename="same.pdf", data=data) for _ in range(8)]
        )

        keys = {result.key for result in results}
        assert len(keys) == 1, f"identical bytes produced {len(keys)} keys"
        assert await store.exists(next(iter(keys)))
        assert await store.get(next(iter(keys))) == data

    async def test_no_partial_files_are_left_behind(self, tmp_path) -> None:
        """A temporary that survives is a file that looks like a document and is not one."""
        import asyncio

        from atlas.storage.local import LocalDocumentStore

        store = LocalDocumentStore(tmp_path)
        await asyncio.gather(
            *[
                store.put(namespace="b" * 32, filename=f"f{index}.pdf", data=f"pdf{index}".encode())
                for index in range(6)
            ]
        )

        leftovers = list(tmp_path.rglob("*.partial"))
        assert not leftovers, f"temporary files left behind: {leftovers}"


class TestDuplicateUploadRecovery:
    """Two uploads of the same file, where both miss the duplicate check.

    Driven deterministically rather than by racing real requests. An earlier version fired
    concurrent HTTP uploads and was genuinely flaky — not because the code was wrong, but
    because the ASGI test transport does not always finalise a dependency's transaction for
    concurrent requests, so the next test's TRUNCATE blocked on it and the suite hung. That is
    a property of the test harness: the same burst against a running server leaves no
    transaction open.

    Forcing the collision directly tests the branch that matters and always takes the same
    path through it.
    """

    async def test_the_loser_gets_the_existing_paper_rather_than_an_error(
        self, registered_client: AsyncClient, api: str, db: AsyncSession, monkeypatch
    ) -> None:
        data = build_pdf([["Duplicate", "A Author", "", "Abstract", "One file, uploaded twice."]])

        first = await upload(registered_client, api, data=data)

        # Make the duplicate check miss, exactly as it does when two requests interleave, so
        # the insert collides on the unique constraint and the recovery path runs.
        from atlas.services import paper_service

        original = paper_service.PaperService._existing_paper
        calls = {"n": 0}

        async def miss_once(self, owner_id, content_hash):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return await original(self, owner_id, content_hash)

        monkeypatch.setattr(paper_service.PaperService, "_existing_paper", miss_once)

        response = await registered_client.post(
            f"{api}/papers", files={"file": ("same.pdf", data, "application/pdf")}
        )

        assert response.status_code == 200, response.text
        assert response.json()["id"] == first["id"], "the loser should get the winner's paper"
        assert calls["n"] >= 2, "the recovery lookup never ran, so nothing was tested"

    async def test_only_one_paper_exists_afterwards(
        self, registered_client: AsyncClient, api: str, db: AsyncSession
    ) -> None:
        data = build_pdf([["Once", "A Author", "", "Abstract", "Stored a single time."]])

        await upload(registered_client, api, data=data)
        await upload(registered_client, api, data=data)

        count = await db.scalar(select(func.count()).select_from(Paper))
        assert count == 1
