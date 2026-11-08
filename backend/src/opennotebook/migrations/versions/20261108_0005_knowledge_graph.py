"""M4: knowledge graph (entities, mentions, relations) and wiki pages

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-08 12:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("graph_status", sa.String(length=20), nullable=True))
    op.add_column("sources", sa.Column("graph_model", sa.String(length=400), nullable=True))
    op.add_column("sources", sa.Column("graph_error", sa.Text(), nullable=True))
    op.create_table(
        "entities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("canonical", sa.String(length=300), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "canonical", name="uq_entities_project_canonical"),
    )
    op.create_index("ix_entities_project_id", "entities", ["project_id"])
    op.create_table(
        "entity_mentions",
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("entity_id", "chunk_id"),
    )
    op.create_index("ix_entity_mentions_source_id", "entity_mentions", ["source_id"])
    op.create_index("ix_entity_mentions_chunk_id", "entity_mentions", ["chunk_id"])
    op.create_table(
        "relations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("src_id", sa.UUID(), nullable=False),
        sa.Column("dst_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dst_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["chunk_id"], ["chunks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in ("project_id", "src_id", "dst_id", "source_id"):
        op.create_index(f"ix_relations_{col}", "relations", [col])
    op.create_table(
        "wiki_pages",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=False),
        sa.Column("basis", sa.String(length=64), nullable=False),
        sa.Column("body_md", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_label", sa.String(length=400), nullable=True),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("entity_id", "basis", name="uq_wiki_entity_basis"),
    )
    op.create_index("ix_wiki_pages_entity_id", "wiki_pages", ["entity_id"])


def downgrade() -> None:
    op.drop_table("wiki_pages")
    op.drop_table("relations")
    op.drop_table("entity_mentions")
    op.drop_table("entities")
    for column in ("graph_error", "graph_model", "graph_status"):
        op.drop_column("sources", column)
