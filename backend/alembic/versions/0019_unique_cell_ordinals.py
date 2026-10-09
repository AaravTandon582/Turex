"""one position per cell in a notebook

A cell's ordinal is its position in the analysis, and the order of the cells is the program.
Nothing enforced that two cells could not hold the same one: `add_cell` counted the collection
to choose the next position, and two requests arriving together both counted the same
collection. Six concurrent appends produced ordinals 0, 1, 2, 2, 3, 5, 5, 5 — silently, since
there was no constraint to violate.

The service now serialises those operations on the analysis row, which is the fix. This is the
guarantee: the same defect reintroduced later fails loudly instead of corrupting an order
nobody is watching.

DEFERRABLE INITIALLY DEFERRED because inserting a cell in the middle renumbers the ones below
it one row at a time, and every intermediate state of that renumber collides. Checking at
commit asks the question that actually matters — are the positions unique when the transaction
is done — rather than one that is false halfway through legitimate work.

Revision ID: 0019
Revises: 0018
Created: 2026-09-16
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "uq_analysis_cells_analysis_id_ordinal"


def upgrade() -> None:
    # Existing duplicates have to go first, or the constraint cannot be created. Renumbered
    # from zero in the order the cells already claim, ties broken by creation time and then by
    # id, so the result is the order a reader currently sees and is the same on every replica.
    op.execute(
        """
        WITH ordered AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY analysis_id ORDER BY ordinal, created_at, id
                   ) - 1 AS position
            FROM analysis_cells
        )
        UPDATE analysis_cells AS cells
        SET ordinal = ordered.position
        FROM ordered
        WHERE cells.id = ordered.id AND cells.ordinal <> ordered.position
        """
    )
    op.create_unique_constraint(
        CONSTRAINT,
        "analysis_cells",
        ["analysis_id", "ordinal"],
        deferrable=True,
        initially="DEFERRED",
    )


def downgrade() -> None:
    op.drop_constraint(CONSTRAINT, "analysis_cells", type_="unique")
