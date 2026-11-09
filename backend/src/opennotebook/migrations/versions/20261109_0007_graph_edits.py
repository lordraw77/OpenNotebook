"""Graph editor: manual entity edits, manual relations, deleted-relation tombstones

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 18:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("manual_name", sa.String(length=300), nullable=True))
    op.add_column("entities", sa.Column("hidden", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("entities", sa.Column("merged_into", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_entities_merged_into", "entities", "entities", ["merged_into"], ["id"], ondelete="SET NULL"
    )
    op.alter_column("relations", "chunk_id", existing_type=sa.UUID(), nullable=True)
    op.alter_column("relations", "source_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("relations", sa.Column("manual", sa.Boolean(), server_default="false", nullable=False))
    op.create_table(
        "relation_blocks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("src_id", sa.UUID(), nullable=False),
        sa.Column("dst_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=60), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["src_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["dst_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "src_id", "dst_id", "type", name="uq_relation_blocks"),
    )
    op.create_index("ix_relation_blocks_project_id", "relation_blocks", ["project_id"])


def downgrade() -> None:
    op.drop_table("relation_blocks")
    op.drop_column("relations", "manual")
    op.execute("DELETE FROM relations WHERE source_id IS NULL")
    op.alter_column("relations", "source_id", existing_type=sa.UUID(), nullable=False)
    op.alter_column("relations", "chunk_id", existing_type=sa.UUID(), nullable=False)
    op.drop_constraint("fk_entities_merged_into", "entities", type_="foreignkey")
    op.drop_column("entities", "merged_into")
    op.drop_column("entities", "hidden")
    op.drop_column("entities", "manual_name")
