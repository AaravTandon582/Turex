"""conversations and citations

Revision ID: 0003
Revises: 0002
Created: 2026-08-13 20:36:10.592837
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column(
            "mode",
            sa.Enum(
                "explain",
                "research",
                "critique",
                "ideate",
                "experiment",
                "study",
                "write",
                name="assistant_mode",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("paper_id", sa.UUID(), nullable=True),
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
            name=op.f("fk_conversations_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_conversations_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
    )
    op.create_index(
        "ix_conversations_owner_id_updated_at",
        "conversations",
        ["owner_id", "updated_at"],
        unique=False,
    )
    op.create_index(op.f("ix_conversations_paper_id"), "conversations", ["paper_id"], unique=False)
    op.create_table(
        "conversation_messages",
        sa.Column("conversation_id", sa.UUID(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "assistant", name="message_role", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "explain",
                "research",
                "critique",
                "ideate",
                "experiment",
                "study",
                "write",
                name="assistant_mode",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
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
            ["conversation_id"],
            ["conversations.id"],
            name=op.f("fk_conversation_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation_messages")),
    )
    op.create_index(
        "ix_conversation_messages_conversation_id_created_at",
        "conversation_messages",
        ["conversation_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "message_citations",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("marker", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("paper_id", sa.UUID(), nullable=True),
        sa.Column("paper_title", sa.Text(), nullable=False),
        sa.Column("locator", sa.String(length=200), nullable=False),
        sa.Column("quoted_text", sa.Text(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("used_in_answer", sa.Boolean(), server_default=sa.text("false"), nullable=False),
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
            name=op.f("fk_message_citations_chunk_id_paper_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["conversation_messages.id"],
            name=op.f("fk_message_citations_message_id_conversation_messages"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_message_citations_paper_id_papers"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_message_citations")),
    )
    op.create_index(
        "ix_message_citations_chunk_id", "message_citations", ["chunk_id"], unique=False
    )
    op.create_index(
        "ix_message_citations_message_id_marker",
        "message_citations",
        ["message_id", "marker"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_message_citations_message_id_marker", table_name="message_citations")
    op.drop_index("ix_message_citations_chunk_id", table_name="message_citations")
    op.drop_table("message_citations")
    op.drop_index(
        "ix_conversation_messages_conversation_id_created_at", table_name="conversation_messages"
    )
    op.drop_table("conversation_messages")
    op.drop_index(op.f("ix_conversations_paper_id"), table_name="conversations")
    op.drop_index("ix_conversations_owner_id_updated_at", table_name="conversations")
    op.drop_table("conversations")
