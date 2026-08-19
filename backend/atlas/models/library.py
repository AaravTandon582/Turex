"""Ways a user organises their library: collections and tags.

Both are owner-scoped. Two users may each have a collection called "Reading list" without
colliding, and neither can see the other's.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from atlas.db.base import Base, OwnedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from atlas.models.paper import Paper


class Collection(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A named group of papers. A paper may belong to any number of collections."""

    __tablename__ = "collections"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_collections_owner_id_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    entries: Mapped[list[CollectionPaper]] = relationship(
        back_populates="collection", cascade="all, delete-orphan", passive_deletes=True
    )


class CollectionPaper(Base):
    """Membership of a paper in a collection.

    An explicit model rather than a bare association table so the join carries `added_at` —
    "recently added to this collection" is a view users ask for.
    """

    __tablename__ = "collection_papers"
    __table_args__ = (Index("ix_collection_papers_paper_id", "paper_id"),)

    collection_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("collections.id", ondelete="CASCADE"),
        primary_key=True,
    )
    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    collection: Mapped[Collection] = relationship(back_populates="entries")
    paper: Mapped[Paper] = relationship()


class Tag(UUIDPrimaryKeyMixin, TimestampMixin, OwnedMixin, Base):
    """A free-form label. Lighter than a collection — no description, no ordering."""

    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_tags_owner_id_name"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False)


class PaperTag(Base):
    __tablename__ = "paper_tags"
    __table_args__ = (Index("ix_paper_tags_tag_id", "tag_id"),)

    paper_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("papers.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True
    )
