"""catalog papers

A wide, shallow index of papers Turex knows about but has not read — see
`turex/models/catalog.py` for why this is separate from `papers` rather than a flag on it.

The search vector is maintained by a trigger rather than a generated column: PostgreSQL only
allows immutable expressions in a generated column, and `setweight(to_tsvector(...))` over two
columns is not accepted there. The guarantee that matters is preserved either way — nothing in
the application writes the column, so nothing in the application can forget to.

Revision ID: 0014
Revises: 0013
Created: 2026-08-20 09:12:41.883210
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REFRESH_FUNCTION = """
CREATE OR REPLACE FUNCTION catalog_papers_refresh_search_tsv() RETURNS trigger AS $$
BEGIN
    NEW.search_tsv :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.abstract, '')), 'B');
    RETURN NEW;
END
$$ LANGUAGE plpgsql;
"""

_TRIGGER = """
CREATE TRIGGER catalog_papers_search_tsv
BEFORE INSERT OR UPDATE OF title, abstract ON catalog_papers
FOR EACH ROW EXECUTE FUNCTION catalog_papers_refresh_search_tsv();
"""


def upgrade() -> None:
    op.create_table(
        "catalog_papers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("arxiv_id", sa.String(length=64), nullable=False),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column(
            "authors", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False
        ),
        sa.Column(
            "categories",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("primary_category", sa.String(length=32), nullable=True),
        sa.Column("journal_ref", sa.Text(), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("published_on", sa.Date(), nullable=True),
        sa.Column("updated_on", sa.Date(), nullable=True),
        # Not-null with no default: the trigger fills it before the constraint is checked,
        # so an insert that omits it succeeds and an insert that sets it to NULL does not.
        sa.Column("search_tsv", postgresql.TSVECTOR(), nullable=False),
        sa.Column(
            "harvested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_papers")),
        sa.UniqueConstraint("arxiv_id", name=op.f("uq_catalog_papers_arxiv_id")),
    )
    op.execute(_REFRESH_FUNCTION)
    op.execute(_TRIGGER)

    op.create_index(op.f("ix_catalog_papers_doi"), "catalog_papers", ["doi"])
    op.create_index(
        "ix_catalog_papers_primary_category_published_on",
        "catalog_papers",
        ["primary_category", "published_on"],
    )
    op.create_index("ix_catalog_papers_published_on", "catalog_papers", ["published_on"])
    op.create_index(
        "ix_catalog_papers_categories",
        "catalog_papers",
        ["categories"],
        postgresql_using="gin",
        postgresql_ops={"categories": "jsonb_path_ops"},
    )
    op.create_index(
        "ix_catalog_papers_search_tsv", "catalog_papers", ["search_tsv"], postgresql_using="gin"
    )


def downgrade() -> None:
    op.drop_index("ix_catalog_papers_search_tsv", table_name="catalog_papers")
    op.drop_index("ix_catalog_papers_categories", table_name="catalog_papers")
    op.drop_index("ix_catalog_papers_published_on", table_name="catalog_papers")
    op.drop_index("ix_catalog_papers_primary_category_published_on", table_name="catalog_papers")
    op.drop_index(op.f("ix_catalog_papers_doi"), table_name="catalog_papers")
    # The trigger goes with the table; the function does not, so it is dropped by name.
    op.drop_table("catalog_papers")
    op.execute("DROP FUNCTION IF EXISTS catalog_papers_refresh_search_tsv()")
