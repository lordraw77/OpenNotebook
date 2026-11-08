"""sources chunks notes

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06 06:50:35.434879
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("notebook_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("indexed", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notebook_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_notes_notebook_id"), "notes", ["notebook_id"], unique=False)
    op.create_table(
        "sources",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("notebook_id", sa.UUID(), nullable=False),
        sa.Column("parent_source_id", sa.UUID(), nullable=True),
        sa.Column("note_id", sa.UUID(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum("file", "code", "image", "web", "note", "archive", name="source_kind"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("original_path", sa.Text(), nullable=True),
        sa.Column("uri", sa.Text(), nullable=True),
        sa.Column("mime_type", sa.String(length=200), nullable=True),
        sa.Column("language", sa.String(length=50), nullable=True),
        sa.Column("content_sha256", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "parsing", "chunking", "embedding", "ready", "failed", name="source_status"),
            nullable=False,
        ),
        sa.Column("error", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pipeline_version", sa.String(length=20), nullable=True),
        sa.Column("embedding_model_id", sa.UUID(), nullable=True),
        sa.Column("vector_collection", sa.String(length=200), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["embedding_model_id"], ["provider_models.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["note_id"], ["notes.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["notebook_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id"),
    )
    op.create_index(op.f("ix_sources_notebook_id"), "sources", ["notebook_id"], unique=False)
    op.create_index(
        "ix_sources_status_open",
        "sources",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status NOT IN ('ready','failed')"),
    )
    op.create_index(
        "uq_sources_notebook_hash",
        "sources",
        ["notebook_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND kind <> 'note'"),
    )
    op.create_table(
        "chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("heading_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("bboxes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=30), nullable=False),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_id", "ordinal", name="uq_chunks_source_ordinal"),
    )
    op.create_index(op.f("ix_chunks_source_id"), "chunks", ["source_id"], unique=False)
    op.create_index("ix_chunks_tsv", "chunks", ["tsv"], unique=False, postgresql_using="gin")
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("provider_model", sa.String(length=400), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_ingestion_jobs_created_at"), "ingestion_jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_ingestion_jobs_source_id"), "ingestion_jobs", ["source_id"], unique=False)
    op.create_table(
        "source_blobs",
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=30), nullable=False),
        sa.Column("object_key", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "role"),
    )


def downgrade() -> None:
    op.drop_table("source_blobs")
    op.drop_index(op.f("ix_ingestion_jobs_source_id"), table_name="ingestion_jobs")
    op.drop_index(op.f("ix_ingestion_jobs_created_at"), table_name="ingestion_jobs")
    op.drop_table("ingestion_jobs")
    op.drop_index("ix_chunks_tsv", table_name="chunks", postgresql_using="gin")
    op.drop_index(op.f("ix_chunks_source_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_index(
        "uq_sources_notebook_hash",
        table_name="sources",
        postgresql_where=sa.text("deleted_at IS NULL AND kind <> 'note'"),
    )
    op.drop_index(
        "ix_sources_status_open",
        table_name="sources",
        postgresql_where=sa.text("status NOT IN ('ready','failed')"),
    )
    op.drop_index(op.f("ix_sources_notebook_id"), table_name="sources")
    op.drop_table("sources")
    op.drop_index(op.f("ix_notes_notebook_id"), table_name="notes")
    op.drop_table("notes")
    op.execute("DROP TYPE IF EXISTS source_kind")
    op.execute("DROP TYPE IF EXISTS source_status")
