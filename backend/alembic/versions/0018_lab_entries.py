"""lab entries

An append-only notebook: entries are written once and never updated, and each carries the hash
of the one before it so that altering any of them breaks every entry after it. See
`turex/models/lab.py` for what that proves and what it does not.

Revision ID: 36886e0f4863
Revises: 0017
Created: 2026-08-21 17:44:21.604055
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lab_entries",
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("experiment_id", sa.UUID(), nullable=True),
        sa.Column("paper_id", sa.UUID(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("previous_hash", sa.String(length=64), nullable=False),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_lab_entries_experiment_id_experiments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_lab_entries_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_lab_entries_paper_id_papers"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_lab_entries_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lab_entries")),
        sa.UniqueConstraint("owner_id", "sequence", name="uq_lab_entries_owner_id_sequence"),
    )
    op.create_index(op.f("ix_lab_entries_owner_id"), "lab_entries", ["owner_id"], unique=False)
    # PostgreSQL does not index a foreign key just because it is one, and deleting a
    # referenced row then scans every table that points at it.
    op.create_index(
        op.f("ix_lab_entries_experiment_id"), "lab_entries", ["experiment_id"], unique=False
    )
    op.create_index(op.f("ix_lab_entries_paper_id"), "lab_entries", ["paper_id"], unique=False)
    op.create_index(
        "ix_lab_entries_owner_id_sequence", "lab_entries", ["owner_id", "sequence"], unique=False
    )
    op.create_index(
        "ix_lab_entries_project_id_recorded_at",
        "lab_entries",
        ["project_id", "recorded_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_lab_entries_project_id_recorded_at", table_name="lab_entries")
    op.drop_index("ix_lab_entries_owner_id_sequence", table_name="lab_entries")
    op.drop_index(op.f("ix_lab_entries_paper_id"), table_name="lab_entries")
    op.drop_index(op.f("ix_lab_entries_experiment_id"), table_name="lab_entries")
    op.drop_index(op.f("ix_lab_entries_owner_id"), table_name="lab_entries")
    op.drop_table("lab_entries")
