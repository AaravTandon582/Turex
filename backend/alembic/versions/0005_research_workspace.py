"""research workspace

Revision ID: 0005
Revises: 0004
Created: 2026-08-13 21:02:34.065360
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("research_question", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active", "paused", "complete", name="project_status", native_enum=False, length=32
            ),
            nullable=False,
        ),
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
            ["owner_id"], ["users.id"], name=op.f("fk_projects_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
    )
    op.create_index(
        "ix_projects_owner_id_updated_at", "projects", ["owner_id", "updated_at"], unique=False
    )
    op.create_table(
        "hypotheses",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("motivation", sa.Text(), nullable=True),
        sa.Column("assumptions", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "proposed",
                "testing",
                "supported",
                "weakly_supported",
                "contradicted",
                "abandoned",
                name="hypothesis_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_hypotheses_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_hypotheses_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_hypotheses")),
    )
    op.create_index(
        "ix_hypotheses_project_id_position", "hypotheses", ["project_id", "position"], unique=False
    )
    op.create_table(
        "project_papers",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("relevance_note", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_project_papers_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_papers_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("project_id", "paper_id", name=op.f("pk_project_papers")),
    )
    op.create_index("ix_project_papers_paper_id", "project_papers", ["paper_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column(
            "status",
            sa.Enum("todo", "doing", "done", name="task_status", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            ["owner_id"], ["users.id"], name=op.f("fk_tasks_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_tasks_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index("ix_tasks_project_id_status", "tasks", ["project_id", "status"], unique=False)
    op.create_table(
        "experiments",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("hypothesis_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("objective", sa.Text(), nullable=True),
        sa.Column("independent_variables", sa.Text(), nullable=True),
        sa.Column("dependent_variables", sa.Text(), nullable=True),
        sa.Column("controls", sa.Text(), nullable=True),
        sa.Column("confounders", sa.Text(), nullable=True),
        sa.Column("dataset", sa.Text(), nullable=True),
        sa.Column("methodology", sa.Text(), nullable=True),
        sa.Column("metrics", sa.Text(), nullable=True),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("actual_result", sa.Text(), nullable=True),
        sa.Column("interpretation", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "running",
                "complete",
                "abandoned",
                name="experiment_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("run_on", sa.Date(), nullable=True),
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
            ["hypothesis_id"],
            ["hypotheses.id"],
            name=op.f("fk_experiments_hypothesis_id_hypotheses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_experiments_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_experiments_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_experiments")),
    )
    op.create_index(
        op.f("ix_experiments_hypothesis_id"), "experiments", ["hypothesis_id"], unique=False
    )
    op.create_index(
        "ix_experiments_project_id_created_at",
        "experiments",
        ["project_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "notes",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("content", sa.Text(), server_default="", nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("paper_id", sa.UUID(), nullable=True),
        sa.Column("hypothesis_id", sa.UUID(), nullable=True),
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
            ["hypothesis_id"],
            ["hypotheses.id"],
            name=op.f("fk_notes_hypothesis_id_hypotheses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_notes_owner_id_users"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"], ["papers.id"], name=op.f("fk_notes_paper_id_papers"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_notes_project_id_projects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notes")),
    )
    op.create_index(
        "ix_notes_owner_id_updated_at", "notes", ["owner_id", "updated_at"], unique=False
    )
    op.create_index("ix_notes_paper_id", "notes", ["paper_id"], unique=False)
    op.create_index("ix_notes_project_id", "notes", ["project_id"], unique=False)
    op.create_table(
        "evidence",
        sa.Column("hypothesis_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("paper_id", sa.UUID(), nullable=True),
        sa.Column(
            "stance",
            sa.Enum(
                "supports", "contradicts", name="evidence_stance", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("paper_title", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=200), nullable=False),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=True),
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
            ["chunk_id"],
            ["paper_chunks.id"],
            name=op.f("fk_evidence_chunk_id_paper_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            name=op.f("fk_evidence_hypothesis_id_hypotheses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_evidence_paper_id_papers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence")),
        sa.UniqueConstraint("hypothesis_id", "chunk_id", name="uq_evidence_hypothesis_id_chunk_id"),
    )
    op.create_index(
        "ix_evidence_hypothesis_id_stance", "evidence", ["hypothesis_id", "stance"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_evidence_hypothesis_id_stance", table_name="evidence")
    op.drop_table("evidence")
    op.drop_index("ix_notes_project_id", table_name="notes")
    op.drop_index("ix_notes_paper_id", table_name="notes")
    op.drop_index("ix_notes_owner_id_updated_at", table_name="notes")
    op.drop_table("notes")
    op.drop_index("ix_experiments_project_id_created_at", table_name="experiments")
    op.drop_index(op.f("ix_experiments_hypothesis_id"), table_name="experiments")
    op.drop_table("experiments")
    op.drop_index("ix_tasks_project_id_status", table_name="tasks")
    op.drop_table("tasks")
    op.drop_index("ix_project_papers_paper_id", table_name="project_papers")
    op.drop_table("project_papers")
    op.drop_index("ix_hypotheses_project_id_position", table_name="hypotheses")
    op.drop_table("hypotheses")
    op.drop_index("ix_projects_owner_id_updated_at", table_name="projects")
    op.drop_table("projects")
