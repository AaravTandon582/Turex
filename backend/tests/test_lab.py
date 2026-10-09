"""The lab notebook: entries that cannot be quietly changed.

Every other record in Turex is editable, because a note whose author cannot fix a typo is a
note nobody writes in. This one is not, and the exception is the entire point: its value in an
authorship dispute comes from what it says today being what it said when it was written.

So the tests are about that property and nothing else. Two kinds:

* **There is no way in.** No update route, no delete route — asserted against the application's
  own route table rather than by remembering not to add one.
* **Tampering is detectable anyway.** Someone with database access can change a row whatever
  the API allows, so the chain is verified against edits, deletions, reorderings and forgeries
  applied directly to the table.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from turex.models.lab import GENESIS_HASH, LabEntry
from turex.models.user import User
from turex.services.lab_service import LabService


@pytest.fixture
async def service(db: AsyncSession) -> LabService:
    return LabService(db)


@pytest.fixture
async def owner(db: AsyncSession) -> User:
    user = User(email="scientist@turex.dev", full_name="Scientist", password_hash="x")
    db.add(user)
    await db.flush()
    return user


async def _write(service: LabService, owner: User, count: int) -> list[LabEntry]:
    return [
        await service.append(owner_id=owner.id, body=f"Observation {index}", title=f"Day {index}")
        for index in range(1, count + 1)
    ]


class TestTheChainIsWellFormed:
    async def test_the_first_entry_starts_from_a_known_beginning(
        self, service: LabService, owner: User
    ) -> None:
        """A defined genesis rather than a null, so the first entry's hash covers something and
        a verifier has no special case to skip."""
        [first] = await _write(service, owner, 1)
        assert first.sequence == 1
        assert first.previous_hash == GENESIS_HASH
        assert first.entry_hash == first.compute_hash()

    async def test_each_entry_points_at_the_one_before_it(
        self, service: LabService, owner: User
    ) -> None:
        entries = await _write(service, owner, 4)
        for previous, entry in pairwise(entries):
            assert entry.previous_hash == previous.entry_hash
            assert entry.sequence == previous.sequence + 1

    async def test_a_fresh_chain_verifies(self, service: LabService, owner: User) -> None:
        await _write(service, owner, 5)
        report = await service.verify(owner.id)

        assert report.intact is True
        assert report.entries == 5
        assert report.breaks == []

    async def test_an_empty_notebook_is_intact_rather_than_broken(
        self, service: LabService, owner: User
    ) -> None:
        """Nothing to verify is not the same as failing to verify."""
        report = await service.verify(owner.id)
        assert report.intact is True
        assert report.entries == 0

    async def test_each_account_has_its_own_chain(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """One shared chain would mean one person's entry could break another's verification."""
        other = User(email="other-lab@turex.dev", full_name="Other", password_hash="x")
        db.add(other)
        await db.flush()

        await _write(service, owner, 3)
        theirs = await service.append(owner_id=other.id, body="Their first entry")

        assert theirs.sequence == 1
        assert theirs.previous_hash == GENESIS_HASH

    async def test_an_empty_entry_is_refused(self, service: LabService, owner: User) -> None:
        """It would take a position and a hash without recording anything."""
        with pytest.raises(Exception, match="needs something written"):
            await service.append(owner_id=owner.id, body="   \n  ")

    async def test_an_entry_cannot_be_filed_under_someone_elses_project(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        from turex.models.workspace import Project

        stranger = User(email="stranger-lab@turex.dev", full_name="S", password_hash="x")
        db.add(stranger)
        await db.flush()
        theirs = Project(owner_id=stranger.id, name="Theirs")
        db.add(theirs)
        await db.flush()

        with pytest.raises(Exception, match="isn't in your workspace"):
            await service.append(owner_id=owner.id, body="x", project_id=theirs.id)


class TestTamperingIsDetected:
    """Whatever the API allows, a row can be changed by anyone with database access. These
    apply exactly that kind of change and require the chain to notice."""

    async def test_rewriting_an_entry_breaks_its_own_hash(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        await _write(service, owner, 4)
        await db.execute(
            text("UPDATE lab_entries SET body = :body WHERE owner_id = :owner AND sequence = 2"),
            {"body": "A much better result than was actually observed.", "owner": owner.id},
        )
        db.expunge_all()

        report = await service.verify(owner.id)
        assert report.intact is False
        assert report.first_break_at == 2
        assert any("no longer matches its own hash" in b.reason for b in report.breaks)

    async def test_moving_a_timestamp_breaks_the_hash(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """Backdating an entry is the specific forgery a lab notebook exists to prevent."""
        await _write(service, owner, 3)
        await db.execute(
            text("UPDATE lab_entries SET recorded_at = :when WHERE owner_id = :o AND sequence = 1"),
            {"when": datetime.now(UTC) - timedelta(days=400), "o": owner.id},
        )
        db.expunge_all()

        assert (await service.verify(owner.id)).intact is False

    async def test_changing_a_title_breaks_the_hash(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """The title is inside the hash too, so it cannot be edited while the body stands."""
        await _write(service, owner, 2)
        await db.execute(
            text("UPDATE lab_entries SET title = :t WHERE owner_id = :o AND sequence = 1"),
            {"t": "A different day entirely", "o": owner.id},
        )
        db.expunge_all()

        assert (await service.verify(owner.id)).intact is False

    async def test_deleting_an_entry_leaves_a_gap_that_is_reported(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """No code path deletes one, so a gap means something reached the table directly."""
        await _write(service, owner, 4)
        await db.execute(
            text("DELETE FROM lab_entries WHERE owner_id = :o AND sequence = 3"),
            {"o": owner.id},
        )
        db.expunge_all()

        report = await service.verify(owner.id)
        assert report.intact is False
        assert report.entries == 3
        assert any("missing before it" in b.reason for b in report.breaks)

    async def test_recomputing_a_hash_still_breaks_the_link_to_the_next_entry(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """The attack a naive per-row hash would miss.

        Someone who edits an entry *and* recomputes its hash makes that entry self-consistent.
        The chain still catches it, because the next entry recorded the old hash — which is the
        whole reason entries are linked rather than hashed independently.
        """
        entries = await _write(service, owner, 3)
        second = entries[1]

        forged = LabEntry(
            sequence=second.sequence,
            title=second.title,
            body="Rewritten, with a matching hash.",
            recorded_at=second.recorded_at,
            previous_hash=second.previous_hash,
        )
        await db.execute(
            text(
                "UPDATE lab_entries SET body = :body, entry_hash = :hash "
                "WHERE owner_id = :o AND sequence = 2"
            ),
            {"body": forged.body, "hash": forged.compute_hash(), "o": owner.id},
        )
        db.expunge_all()

        report = await service.verify(owner.id)
        assert report.intact is False
        assert any("an earlier entry changed" in b.reason for b in report.breaks)

    async def test_verification_names_where_it_first_went_wrong(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """ "Something is wrong" is not usable in a dispute; "entry 7, on this date" is."""
        await _write(service, owner, 8)
        await db.execute(
            text("UPDATE lab_entries SET body = 'x' WHERE owner_id = :o AND sequence = 7"),
            {"o": owner.id},
        )
        db.expunge_all()

        report = await service.verify(owner.id)
        assert report.first_break_at == 7
        assert report.breaks[0].recorded_at is not None


class TestThereIsNoWayToChangeOne:
    async def test_the_api_offers_no_update_or_delete(self, app: object) -> None:
        """Asserted against the route table, not by remembering. An endpoint that exists is an
        endpoint that can be reached, and this is the one table where that must not be true."""
        schema = app.openapi()  # type: ignore[attr-defined]

        mutating = {
            (method.upper(), path)
            for path, operations in schema["paths"].items()
            for method in operations
            if path.startswith("/api/v1/lab/") and method.upper() in {"PUT", "PATCH", "DELETE"}
        }
        assert mutating == set(), f"the lab notebook must be append-only, found {mutating}"

    async def test_appending_and_verifying_over_http(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        for index in range(3):
            created = await registered_client.post(
                f"{api}/lab/entries",
                json={"title": f"Day {index}", "body": f"Observation {index}"},
            )
            assert created.status_code == 201

        report = (await registered_client.get(f"{api}/lab/verify")).json()
        assert report["intact"] is True
        assert report["entries"] == 3

    async def test_both_hashes_are_returned_so_the_chain_can_be_checked_elsewhere(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        """Evidence nobody can check independently is not evidence."""
        entry = (
            await registered_client.post(f"{api}/lab/entries", json={"body": "Something"})
        ).json()

        assert len(entry["entry_hash"]) == 64
        assert entry["previous_hash"] == GENESIS_HASH

    async def test_one_account_cannot_read_anothers_notebook(
        self, registered_client: AsyncClient, other_client: AsyncClient, api: str
    ) -> None:
        await registered_client.post(f"{api}/lab/entries", json={"body": "Private observation"})

        theirs = (await other_client.get(f"{api}/lab/entries")).json()
        assert theirs["total"] == 0

    async def test_an_unknown_project_filter_returns_nothing_rather_than_everything(
        self, registered_client: AsyncClient, api: str
    ) -> None:
        await registered_client.post(f"{api}/lab/entries", json={"body": "Loose entry"})

        page = (await registered_client.get(f"{api}/lab/entries?project_id={uuid.uuid4()}")).json()
        assert page["total"] == 0


class TestConcurrentAppends:
    async def test_two_entries_never_take_the_same_position(
        self, service: LabService, owner: User, db: AsyncSession
    ) -> None:
        """A fork makes the chain unverifiable, which is worse than having none — it still
        looks like evidence."""
        await _write(service, owner, 6)

        sequences = (
            (await db.execute(select(LabEntry.sequence).where(LabEntry.owner_id == owner.id)))
            .scalars()
            .all()
        )

        assert sorted(sequences) == list(range(1, 7))
        assert len(set(sequences)) == len(sequences)


class TestAppendingFromTwoRequestsAtOnce:
    """Two appends arriving together must both be written, in some order.

    Driven through real concurrent sessions rather than concurrent HTTP, because the thing
    under test is two database transactions — and the ASGI transport's handling of concurrent
    requests is the reason an earlier concurrency test in this suite had to be rewritten.

    What this caught: appending locked the last entry `FOR UPDATE`, which reads correctly and
    does not work. A row lock stops that row changing; it does not stop a newer one being
    inserted. The second transaction waited, re-read the row it had been waiting for rather
    than the later one just written, and computed a sequence that was already taken. Eight
    concurrent appends returned five 500s.
    """

    async def test_eight_appends_at_once_are_all_written_and_the_chain_holds(
        self, db: AsyncSession
    ) -> None:
        import asyncio

        from turex.db.session import session_scope

        user = User(email="concurrent@turex.dev", full_name="Concurrent", password_hash="x")
        db.add(user)
        await db.flush()
        await db.commit()
        owner_id = user.id

        async def write(index: int) -> None:
            async with session_scope() as session:
                await LabService(session).append(owner_id=owner_id, body=f"Simultaneous {index}")

        results = await asyncio.gather(
            *[write(index) for index in range(8)], return_exceptions=True
        )
        failures = [result for result in results if isinstance(result, BaseException)]
        assert not failures, f"appends that raced were refused: {failures}"

        async with session_scope() as session:
            report = await LabService(session).verify(owner_id)
            written = list(
                await session.scalars(
                    select(LabEntry)
                    .where(LabEntry.owner_id == owner_id)
                    .order_by(LabEntry.sequence)
                )
            )

        assert len(written) == 8
        # The sequence is what the chain is threaded on: no gaps, no repeats.
        assert [entry.sequence for entry in written] == list(range(1, 9))
        assert report.intact, f"the chain forked: {report.breaks}"
