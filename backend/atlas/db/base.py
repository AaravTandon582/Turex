"""Declarative base, shared column conventions, and mixins."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Deterministic constraint names. Without these, Alembic autogenerate emits unnamed
# constraints that later migrations cannot drop by name.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID primary keys, generated database-side.

    Chosen over serial integers so identifiers can appear in URLs without leaking how many
    users or papers exist, and so a client can reference a row before insertion completes.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class OwnedMixin:
    """A row that belongs to exactly one account.

    Thirteen models declared this same column by hand. Beyond the repetition, each copy was a
    chance to get `ondelete` wrong — and a missing cascade there means a deleted account leaves
    rows behind that no longer have an owner to scope them to, which is the worst kind of
    orphan in a system whose central rule is that everything is owner-scoped.

    The index matters as much as the column: every owner-scoped query filters on it, and
    PostgreSQL does not index a foreign key just because it is one.
    """

    @declared_attr
    def owner_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
