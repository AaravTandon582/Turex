"""an index that matches how the catalog is browsed

Browsing a large category took six to seven seconds at 866,000 rows, and the plan showed the
reason: a bitmap scan finding all 147,000 matches followed by a sort of every one of them, to
return twenty.

There was already an index on `published_on`, and it could not be used. The ordering is
`published_on DESC NULLS LAST`, and a default btree is `ASC NULLS LAST` — walking it backwards
produces `DESC NULLS FIRST`, which is a different order, so PostgreSQL had no choice but to
sort. Spelling the index the way the query spells the ordering lets it walk the index and stop
after twenty rows.

`NULLS LAST` is not negotiable: it is what keeps papers with no date out of the top of a list
sorted by date, and reversing it to suit an index would be letting the storage decide what the
reader sees.

Revision ID: 0017
Revises: 0016
Created: 2026-08-21 02:14:52.118904
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # `external_id` is included because it is the tiebreak. Without it the index serves the
    # first key and then still sorts within each date, which for a busy day is thousands of
    # rows — and the tiebreak exists so that paging cannot show one paper twice and hide
    # another, which is worth keeping.
    op.execute(
        "CREATE INDEX ix_catalog_papers_browse "
        "ON catalog_papers (published_on DESC NULLS LAST, external_id DESC)"
    )
    op.drop_index("ix_catalog_papers_published_on", table_name="catalog_papers")


def downgrade() -> None:
    op.create_index("ix_catalog_papers_published_on", "catalog_papers", ["published_on"])
    op.drop_index("ix_catalog_papers_browse", table_name="catalog_papers")
