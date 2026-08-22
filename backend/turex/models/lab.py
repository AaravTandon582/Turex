"""The lab notebook: entries that cannot be quietly changed.

Every other record in Turex is editable, because a note whose author cannot fix a typo is a
note nobody writes in. A lab notebook is the exception, and the exception is the entire point
of it. Its value in an authorship dispute, a reproducibility challenge, or a patent claim comes
from one property: **what it says today is what it said when it was written.** A notebook you
can edit afterwards proves nothing, because the version you are holding is the only version
anyone can see.

So an entry here is appended and never touched again. There is no update route and no delete
route — not "there is one but it is guarded", genuinely none, because an endpoint that exists
is an endpoint that can be reached.

That alone would still be a promise rather than evidence: anyone with database access could
change a row and nobody could tell. So each entry carries the hash of the one before it,
covering its own text, its timestamp, and its position. Altering any entry changes its hash,
which breaks every entry after it, and `verify` walks the chain and reports exactly where it
stopped matching.

**What that proves and what it does not.** It proves nobody edited an entry *after later ones
were written*, which is the case that matters — a rewritten history is what a dispute is
about. It does not prove *when* an entry was written, because the timestamp is this server's.
Anchoring that would need an outside witness — a timestamping authority, a commit pushed to a
remote — and this is honest about not having one rather than implying otherwise.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from turex.db.base import Base, OwnedMixin, UUIDPrimaryKeyMixin

GENESIS_HASH = "0" * 64
"""What the first entry's `previous_hash` is.

A fixed, known value rather than null: it makes the first entry's hash cover something, so the
chain has a defined beginning that a verifier can check rather than a special case it has to
skip.
"""


def entry_digest(*, sequence: int, recorded_at: datetime, body: str, previous_hash: str) -> str:
    """The hash covering one entry and its place in the chain.

    Every field that would matter in a dispute is inside it. The **sequence** is included so
    entries cannot be reordered; the **timestamp** so a date cannot be moved; the **body**
    obviously; and the **previous hash** so that changing any earlier entry invalidates every
    later one rather than only itself.

    Fields are joined with a separator that cannot occur in the parts. Without one,
    `("ab", "c")` and `("a", "bc")` hash identically — which would let text be moved across a
    boundary without detection. A null byte cannot appear in any of these, so it is the
    separator that cannot be forged.
    """
    payload = "\0".join(
        (
            str(sequence),
            # Microsecond ISO-8601 in UTC. A format that varies by locale or precision would
            # make a hash unreproducible on a different machine, which is where it has to be
            # checked.
            recorded_at.astimezone(tz=None).isoformat(timespec="microseconds"),
            body,
            previous_hash,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LabEntry(UUIDPrimaryKeyMixin, OwnedMixin, Base):
    """One appended entry. Written once, never updated.

    `TimestampMixin` is deliberately not used: it carries an `updated_at`, and a column that
    records when a row last changed has no meaning on a row that cannot change. Its presence
    would suggest the opposite of what this table guarantees.
    """

    __tablename__ = "lab_entries"
    __table_args__ = (
        Index("ix_lab_entries_owner_id_sequence", "owner_id", "sequence"),
        Index("ix_lab_entries_project_id_recorded_at", "project_id", "recorded_at"),
        # One chain per account, with no gaps and no duplicates. The constraint is what makes
        # a concurrent append fail loudly rather than fork the chain into two branches that
        # both claim the same position.
        UniqueConstraint("owner_id", "sequence", name="uq_lab_entries_owner_id_sequence"),
    )

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL")
    )
    """`SET NULL`, not `CASCADE`.

    Deleting a project must not delete the record of what was done in it — that is precisely
    the deletion someone would want in a dispute. The entry survives, unattached, and the
    chain stays intact; a cascade would break every hash after it and destroy the evidence
    for every other project too.
    """

    # Indexed because PostgreSQL does not index a foreign key just because it is one, and an
    # unindexed one makes the referenced row's deletion scan this whole table to find what
    # points at it. `tests/test_query_counts.py` checks every foreign key for this.
    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("experiments.id", ondelete="SET NULL"), index=True
    )
    paper_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="SET NULL"), index=True
    )

    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    """This entry's position in the account's chain, starting at 1."""

    title: Mapped[str | None] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text, nullable=False)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    """When the server recorded it — not when the author says it happened.

    A field the writer controls would be the first thing altered in a dispute. If work happened
    at a different time, that belongs in the body where it reads as a claim rather than as a
    fact the system is vouching for.
    """

    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    def compute_hash(self) -> str:
        """Recompute this entry's hash from its own contents, for verification."""
        return entry_digest(
            sequence=self.sequence,
            recorded_at=self.recorded_at,
            body=self._hashed_body(),
            previous_hash=self.previous_hash,
        )

    def _hashed_body(self) -> str:
        """Title and body together, so a title cannot be changed without breaking the hash."""
        return f"{self.title or ''}\0{self.body}"
