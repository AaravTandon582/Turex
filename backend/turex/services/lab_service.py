"""Appending to the lab notebook, and checking that nothing has been changed.

Two operations, and the second is what makes the first worth anything.

Appending has one hard requirement: **two entries must never take the same position**. If they
did, the chain forks and neither branch can be verified — and a chain that cannot be verified
is a chain that proves nothing, which is worse than not having one, because it looks like
evidence.

Concurrency is therefore handled by locking rather than by hoping. Reading the last entry and
then writing the next one is a read-modify-write, and two requests arriving together will both
read the same last entry and both claim the next position. The unique constraint would catch
it; the lock stops it happening.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from turex.core.errors import NotFoundError, ValidationError
from turex.core.logging import get_logger
from turex.models.lab import GENESIS_HASH, LabEntry
from turex.models.workspace import Experiment, Project

logger = get_logger(__name__)

MAX_BODY_CHARS = 100_000
"""An entry is a record of what was done, not a document store."""


@dataclass(frozen=True, slots=True)
class ChainBreak:
    """One entry whose hash does not match its contents."""

    sequence: int
    entry_id: uuid.UUID
    recorded_at: datetime
    reason: str


@dataclass(frozen=True, slots=True)
class ChainReport:
    """What verification found.

    `intact` is deliberately the only thing a caller should branch on. Everything else is
    detail for a human reading the result, and a report that says "intact except…" is not a
    report anyone should act on programmatically.
    """

    entries: int
    intact: bool
    breaks: list[ChainBreak] = field(default_factory=list)
    first_break_at: int | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class LabService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _serialise_appends(self, owner_id: uuid.UUID) -> None:
        """Hold an append lock for this account until the transaction ends.

        Appending is a read-modify-write: read the last entry, compute the next sequence, hash
        against its hash, insert. Two requests arriving together read the same last entry,
        compute the same sequence, and hash against the same predecessor — a fork, caught only
        by the unique constraint and surfacing as a 500 the caller cannot act on.

        This locked the last *row* before, which does not work and had a comment explaining why
        it did. A row lock stops that row changing; it does not stop a newer one being inserted.
        Under READ COMMITTED the second request waits on the lock, and when it is released
        re-reads the row it was already waiting for — not the later row the first request just
        wrote. It then computes exactly the sequence that was taken. Eight concurrent appends
        returned five 500s.

        An advisory lock has none of that shape: it is keyed on the account rather than on a
        row, so it also covers the first append to an empty chain, where there was no row to
        lock at all. `pg_advisory_xact_lock` releases at commit or rollback, so a failed
        request cannot strand it.
        """
        # The key is the account's own id folded to the signed 64 bits the function takes.
        # Collisions between two accounts cost one of them a short wait, and nothing else.
        key = int.from_bytes(owner_id.bytes[:8], "big") - (1 << 63)
        await self._db.execute(select(func.pg_advisory_xact_lock(key)))

    async def _last(self, owner_id: uuid.UUID) -> LabEntry | None:
        """The most recent entry. Callers that append hold the lock above first."""
        return await self._db.scalar(
            select(LabEntry)
            .where(LabEntry.owner_id == owner_id)
            .order_by(LabEntry.sequence.desc())
            .limit(1)
        )

    async def append(
        self,
        *,
        owner_id: uuid.UUID,
        body: str,
        title: str | None = None,
        project_id: uuid.UUID | None = None,
        experiment_id: uuid.UUID | None = None,
        paper_id: uuid.UUID | None = None,
    ) -> LabEntry:
        """Write an entry. There is no counterpart to this — nothing edits or removes one."""
        text = body.strip()
        if not text:
            # An empty entry is not a record of anything, and it would still take a position in
            # the chain and a hash, which makes the chain longer without making it say more.
            raise ValidationError("A lab entry needs something written in it.")
        if len(text) > MAX_BODY_CHARS:
            raise ValidationError(f"A lab entry holds at most {MAX_BODY_CHARS:,} characters.")

        for model, row_id, label in (
            (Project, project_id, "project"),
            (Experiment, experiment_id, "experiment"),
        ):
            if row_id is not None:
                found = await self._db.scalar(
                    select(model.id).where(model.id == row_id, model.owner_id == owner_id)
                )
                if found is None:
                    raise NotFoundError(f"That {label} isn't in your workspace.")

        await self._serialise_appends(owner_id)

        previous = await self._last(owner_id)
        sequence = (previous.sequence + 1) if previous else 1
        previous_hash = previous.entry_hash if previous else GENESIS_HASH

        # Stamped here rather than by the database default, because the value has to be inside
        # the hash and a server-side default is not known until after the insert.
        recorded_at = datetime.now(UTC)

        entry = LabEntry(
            owner_id=owner_id,
            project_id=project_id,
            experiment_id=experiment_id,
            paper_id=paper_id,
            sequence=sequence,
            title=((title or None) and title.strip()[:300]) or None,
            body=text,
            recorded_at=recorded_at,
            previous_hash=previous_hash,
        )
        entry.entry_hash = entry.compute_hash()

        self._db.add(entry)
        await self._db.flush()

        logger.info(
            "lab entry appended",
            extra={"sequence": sequence, "owner_id": str(owner_id)},
        )
        return entry

    async def list_entries(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[LabEntry], int]:
        """Entries newest first, with the total so a reader knows what they are seeing."""
        conditions = [LabEntry.owner_id == owner_id]
        if project_id is not None:
            conditions.append(LabEntry.project_id == project_id)

        total = int(
            await self._db.scalar(select(func.count()).select_from(LabEntry).where(*conditions))
            or 0
        )
        rows = await self._db.execute(
            select(LabEntry)
            .where(*conditions)
            .order_by(LabEntry.sequence.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows.scalars().all()), total

    async def verify(self, owner_id: uuid.UUID) -> ChainReport:
        """Walk the whole chain and report anything that does not match.

        Every entry, in order, rather than a sample: the point is to be able to say the record
        is whole, and a spot check cannot say that. It is one indexed scan of a table that has
        one row per notebook entry, so a notebook large enough for this to be slow is one
        nobody could read either.

        Three things are checked, and they fail differently on purpose. A **hash mismatch**
        means that entry's own text or timestamp changed. A **broken link** means an earlier
        entry changed. A **gap in the sequence** means an entry was deleted outright — which
        no code path does, so finding one means something reached the database directly.
        """
        rows = await self._db.execute(
            select(LabEntry).where(LabEntry.owner_id == owner_id).order_by(LabEntry.sequence)
        )
        entries = list(rows.scalars().all())

        breaks: list[ChainBreak] = []
        expected_previous = GENESIS_HASH
        expected_sequence = 1

        for entry in entries:
            if entry.sequence != expected_sequence:
                breaks.append(
                    ChainBreak(
                        sequence=entry.sequence,
                        entry_id=entry.id,
                        recorded_at=entry.recorded_at,
                        reason=(
                            f"expected entry {expected_sequence} here — "
                            f"{entry.sequence - expected_sequence} missing before it"
                        ),
                    )
                )
                expected_sequence = entry.sequence

            if entry.previous_hash != expected_previous:
                breaks.append(
                    ChainBreak(
                        sequence=entry.sequence,
                        entry_id=entry.id,
                        recorded_at=entry.recorded_at,
                        reason="does not follow the entry before it — an earlier entry changed",
                    )
                )

            if entry.compute_hash() != entry.entry_hash:
                breaks.append(
                    ChainBreak(
                        sequence=entry.sequence,
                        entry_id=entry.id,
                        recorded_at=entry.recorded_at,
                        reason="its text or timestamp no longer matches its own hash",
                    )
                )

            expected_previous = entry.entry_hash
            expected_sequence = entry.sequence + 1

        return ChainReport(
            entries=len(entries),
            intact=not breaks,
            breaks=breaks,
            first_break_at=breaks[0].sequence if breaks else None,
        )
