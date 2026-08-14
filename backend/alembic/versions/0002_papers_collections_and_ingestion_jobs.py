"""papers collections and ingestion jobs

Revision ID: 0002
Revises: 0001
Created: 2026-08-13 20:02:08.665106
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "collections",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
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
            name=op.f("fk_collections_owner_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_collections")),
        sa.UniqueConstraint("owner_id", "name", name="uq_collections_owner_id_name"),
    )
    op.create_index(op.f("ix_collections_owner_id"), "collections", ["owner_id"], unique=False)
    op.create_table(
        "papers",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "authors",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("abstract", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.Integer(), nullable=True),
        sa.Column("venue", sa.Text(), nullable=True),
        sa.Column("doi", sa.String(length=255), nullable=True),
        sa.Column("arxiv_id", sa.String(length=64), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "upload", "arxiv", "doi", "url", name="paper_source", native_enum=False, length=32
            ),
            nullable=False,
        ),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "processing",
                "ready",
                "failed",
                name="processing_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column(
            "reading_status",
            sa.Enum(
                "unread",
                "reading",
                "read",
                "revisit",
                name="reading_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_favorite", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_opened_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint(
            "page_count IS NULL OR page_count > 0", name=op.f("ck_papers_page_count_positive")
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_papers_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_papers")),
        sa.UniqueConstraint("owner_id", "content_hash", name="uq_papers_owner_id_content_hash"),
    )
    op.create_index(
        "ix_papers_owner_id_created_at", "papers", ["owner_id", "created_at"], unique=False
    )
    op.create_index("ix_papers_owner_id_status", "papers", ["owner_id", "status"], unique=False)
    op.create_table(
        "tags",
        sa.Column("owner_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
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
            ["owner_id"], ["users.id"], name=op.f("fk_tags_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tags")),
        sa.UniqueConstraint("owner_id", "name", name="uq_tags_owner_id_name"),
    )
    op.create_index(op.f("ix_tags_owner_id"), "tags", ["owner_id"], unique=False)
    op.create_table(
        "collection_papers",
        sa.Column("collection_id", sa.UUID(), nullable=False),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"],
            ["collections.id"],
            name=op.f("fk_collection_papers_collection_id_collections"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_collection_papers_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("collection_id", "paper_id", name=op.f("pk_collection_papers")),
    )
    op.create_index(
        "ix_collection_papers_paper_id", "collection_papers", ["paper_id"], unique=False
    )
    op.create_table(
        "ingestion_jobs",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum("ingest_paper", name="job_kind", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                name="job_status",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "stage",
            sa.Enum(
                "queued",
                "extracting_text",
                "reading_structure",
                "extracting_metadata",
                "building_chunks",
                "embedding",
                "complete",
                name="ingestion_stage",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default=sa.text("3"), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=64), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
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
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_ingestion_jobs_attempts_non_negative")),
        sa.CheckConstraint(
            "progress BETWEEN 0 AND 100", name=op.f("ck_ingestion_jobs_progress_within_range")
        ),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_ingestion_jobs_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingestion_jobs")),
    )
    op.create_index(
        "ix_ingestion_jobs_claimable",
        "ingestion_jobs",
        ["status", "scheduled_at"],
        unique=False,
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_index("ix_ingestion_jobs_paper_id", "ingestion_jobs", ["paper_id"], unique=False)
    op.create_table(
        "paper_sections",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
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
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_sections_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_sections")),
        sa.UniqueConstraint("paper_id", "ordinal", name="uq_paper_sections_paper_id_ordinal"),
    )
    op.create_index(
        op.f("ix_paper_sections_paper_id"), "paper_sections", ["paper_id"], unique=False
    )
    op.create_table(
        "paper_tags",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("tag_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_tags_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tag_id"], ["tags.id"], name=op.f("fk_paper_tags_tag_id_tags"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("paper_id", "tag_id", name=op.f("pk_paper_tags")),
    )
    op.create_index("ix_paper_tags_tag_id", "paper_tags", ["tag_id"], unique=False)
    op.create_table(
        "paper_chunks",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("section_id", sa.UUID(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.Vector(dim=1536), nullable=True),
        sa.Column(
            "content_tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', content)", persisted=True),
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
            ["paper_id"],
            ["papers.id"],
            name=op.f("fk_paper_chunks_paper_id_papers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["paper_sections.id"],
            name=op.f("fk_paper_chunks_section_id_paper_sections"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_chunks")),
        sa.UniqueConstraint("paper_id", "ordinal", name="uq_paper_chunks_paper_id_ordinal"),
    )
    op.create_index(
        "ix_paper_chunks_content_tsv",
        "paper_chunks",
        ["content_tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index(
        "ix_paper_chunks_embedding_hnsw",
        "paper_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_paper_chunks_paper_id_ordinal", "paper_chunks", ["paper_id", "ordinal"], unique=False
    )
    op.create_index(
        op.f("ix_paper_chunks_section_id"), "paper_chunks", ["section_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_paper_chunks_section_id"), table_name="paper_chunks")
    op.drop_index("ix_paper_chunks_paper_id_ordinal", table_name="paper_chunks")
    op.drop_index(
        "ix_paper_chunks_embedding_hnsw",
        table_name="paper_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index("ix_paper_chunks_content_tsv", table_name="paper_chunks", postgresql_using="gin")
    op.drop_table("paper_chunks")
    op.drop_index("ix_paper_tags_tag_id", table_name="paper_tags")
    op.drop_table("paper_tags")
    op.drop_index(op.f("ix_paper_sections_paper_id"), table_name="paper_sections")
    op.drop_table("paper_sections")
    op.drop_index("ix_ingestion_jobs_paper_id", table_name="ingestion_jobs")
    op.drop_index(
        "ix_ingestion_jobs_claimable",
        table_name="ingestion_jobs",
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_collection_papers_paper_id", table_name="collection_papers")
    op.drop_table("collection_papers")
    op.drop_index(op.f("ix_tags_owner_id"), table_name="tags")
    op.drop_table("tags")
    op.drop_index("ix_papers_owner_id_status", table_name="papers")
    op.drop_index("ix_papers_owner_id_created_at", table_name="papers")
    op.drop_table("papers")
    op.drop_index(op.f("ix_collections_owner_id"), table_name="collections")
    op.drop_table("collections")
