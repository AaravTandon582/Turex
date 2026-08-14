"""annotations

Revision ID: 0004
Revises: 0003
Created: 2026-08-13 20:52:04.921469
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "annotations",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("text_offset", sa.Integer(), nullable=False),
        sa.Column("text_length", sa.Integer(), nullable=False),
        sa.Column("selected_text", sa.Text(), nullable=False),
        sa.Column(
            "colour",
            sa.Enum(
                "important",
                "question",
                "method",
                "result",
                name="highlight_colour",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.CheckConstraint("page_number >= 1", name=op.f("ck_annotations_page_number_positive")),
        sa.CheckConstraint("text_length > 0", name=op.f("ck_annotations_text_length_positive")),
        sa.CheckConstraint(
            "text_offset >= 0", name=op.f("ck_annotations_text_offset_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["users.id"],
            name=op.f("fk_annotations_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_annotations_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_annotations")),
    )
    op.create_index(
        "ix_annotations_owner_id_created_at",
        "annotations",
        ["owner_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_annotations_paper_id_page_number",
        "annotations",
        ["paper_id", "page_number"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_annotations_paper_id_page_number", table_name="annotations")
    op.drop_index("ix_annotations_owner_id_created_at", table_name="annotations")
    op.drop_table("annotations")
