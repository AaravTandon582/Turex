"""catalog sources

The catalog was arXiv-shaped: `arxiv_id` was the key, and both URLs were derived from it. arXiv
has no medicine, no chemistry, and no humanities, so one source was never going to answer "find
me any paper" — see `atlas/models/catalog.py`.

`arxiv_id` becomes `external_id`, unique *per source* rather than globally, and the two URLs
become stored columns because only arXiv's are a pure function of the id.

Existing rows are all arXiv, so they are carried across rather than rebuilt: the ids are
already correct and the URLs are recomputed from them by the same rule the property used. At
389,000 rows a re-harvest would be hours; this is one UPDATE.

Revision ID: 0016
Revises: 0015
Created: 2026-08-21 00:31:07.442901
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_papers",
        sa.Column(
            "source",
            sa.Enum("arxiv", "openalex", name="catalog_source", native_enum=False, length=32),
            server_default="arxiv",
            nullable=False,
        ),
    )
    op.add_column("catalog_papers", sa.Column("pdf_url", sa.Text(), nullable=True))
    op.add_column("catalog_papers", sa.Column("landing_url", sa.Text(), nullable=True))

    # Renamed rather than added-and-copied: the column already holds exactly the right values,
    # and a rename keeps them without touching a row.
    op.alter_column(
        "catalog_papers", "arxiv_id", new_column_name="external_id", type_=sa.String(length=128)
    )

    # The URLs the old property derived, materialised once for the rows that already exist.
    op.execute(
        """
        UPDATE catalog_papers
        SET pdf_url = 'https://arxiv.org/pdf/' || external_id,
            landing_url = 'https://arxiv.org/abs/' || external_id
        WHERE source = 'arxiv'
        """
    )

    # Uniqueness moves from the id alone to the pair. An arXiv id and an OpenAlex id can never
    # collide in practice, but relying on that is relying on two organisations never changing
    # their id formats, which is not a guarantee anyone has given.
    op.drop_constraint("uq_catalog_papers_arxiv_id", "catalog_papers", type_="unique")
    op.create_unique_constraint(
        "uq_catalog_papers_source_external_id", "catalog_papers", ["source", "external_id"]
    )


def downgrade() -> None:
    # Only arXiv entries can exist in the old shape — its key was the arXiv id and its URLs
    # were derived from one. Anything harvested from another source has no representation
    # there at all, so it is removed rather than given a fabricated arXiv id that resolves to
    # a different paper, or to nothing.
    op.execute("DELETE FROM catalog_papers WHERE source <> 'arxiv'")

    op.drop_constraint("uq_catalog_papers_source_external_id", "catalog_papers", type_="unique")
    op.alter_column(
        "catalog_papers", "external_id", new_column_name="arxiv_id", type_=sa.String(length=64)
    )
    op.create_unique_constraint("uq_catalog_papers_arxiv_id", "catalog_papers", ["arxiv_id"])

    op.drop_column("catalog_papers", "landing_url")
    op.drop_column("catalog_papers", "pdf_url")
    op.drop_column("catalog_papers", "source")
