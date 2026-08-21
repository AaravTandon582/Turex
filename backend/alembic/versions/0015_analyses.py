"""analyses and cells

The computational half of a project: a notebook of cells, each holding code and the output it
last produced. Nothing here is executed by the server — the code runs in the reader's browser,
in Python compiled to WebAssembly, and only text comes back. See `turex/models/analysis.py`.

Revision ID: e970b8971889
Revises: 0014
Created: 2026-08-20 23:20:53.195656
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("experiment_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            name=op.f("fk_analyses_experiment_id_experiments"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_analyses_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_analyses_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
    )
    op.create_index(op.f("ix_analyses_experiment_id"), "analyses", ["experiment_id"], unique=False)
    op.create_index(op.f("ix_analyses_owner_id"), "analyses", ["owner_id"], unique=False)
    op.create_index(
        "ix_analyses_project_id_created_at", "analyses", ["project_id", "created_at"], unique=False
    )
    op.create_table(
        "analysis_cells",
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("code", "markdown", name="cell_kind", native_enum=False, length=32),
            server_default="code",
            nullable=False,
        ),
        sa.Column("source", sa.Text(), server_default="", nullable=False),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("image", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "idle", "ok", "error", "stale", name="cell_status", native_enum=False, length=32
            ),
            server_default="idle",
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_analysis_cells_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_cells")),
    )
    op.create_index(
        "ix_analysis_cells_analysis_id_ordinal",
        "analysis_cells",
        ["analysis_id", "ordinal"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_cells_analysis_id_ordinal", table_name="analysis_cells")
    op.drop_table("analysis_cells")
    op.drop_index("ix_analyses_project_id_created_at", table_name="analyses")
    op.drop_index(op.f("ix_analyses_owner_id"), table_name="analyses")
    op.drop_index(op.f("ix_analyses_experiment_id"), table_name="analyses")
    op.drop_table("analyses")
