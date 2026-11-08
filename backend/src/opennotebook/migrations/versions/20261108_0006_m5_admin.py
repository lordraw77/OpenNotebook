"""M5: groups metadata, OIDC subject, project settings (provider policy, serving embedding index)

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-08 15:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("groups", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("groups", sa.Column("source", sa.String(length=20), server_default="local", nullable=False))
    op.add_column("users", sa.Column("oidc_subject", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_users_oidc_subject", "users", ["oidc_subject"])
    op.create_table(
        "project_settings",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("allowed_provider_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("embedding_model_id", sa.UUID(), nullable=True),
        sa.Column("index_switched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["embedding_model_id"], ["provider_models.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("project_id"),
    )
    # Existing projects: the index that serves searches today is the one their sources were embedded with.
    op.execute(
        """
        INSERT INTO project_settings (project_id, embedding_model_id)
        SELECT DISTINCT ON (p.id) p.id, s.embedding_model_id
        FROM nodes p
        JOIN nodes nb ON nb.path <@ p.path
        JOIN sources s ON s.notebook_id = nb.id
        WHERE p.kind = 'project' AND s.embedding_model_id IS NOT NULL AND s.deleted_at IS NULL
        ORDER BY p.id, s.indexed_at DESC NULLS LAST
        """
    )


def downgrade() -> None:
    op.drop_table("project_settings")
    op.drop_constraint("uq_users_oidc_subject", "users", type_="unique")
    op.drop_column("users", "oidc_subject")
    op.drop_column("groups", "source")
    op.drop_column("groups", "description")
