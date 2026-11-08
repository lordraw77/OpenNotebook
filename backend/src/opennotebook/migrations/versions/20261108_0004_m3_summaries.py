"""M3: source summaries and suggested questions; index on archive / crawl children

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08 09:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "sources",
        sa.Column(
            "suggested_questions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("sources", sa.Column("summary_status", sa.String(length=20), nullable=True))
    op.add_column("sources", sa.Column("summary_model", sa.String(length=400), nullable=True))
    op.add_column("sources", sa.Column("summary_error", sa.Text(), nullable=True))
    op.create_index(
        "ix_sources_parent_source_id",
        "sources",
        ["parent_source_id"],
        postgresql_where=sa.text("parent_source_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_sources_parent_source_id", table_name="sources")
    for column in ("summary_error", "summary_model", "summary_status", "suggested_questions", "summary"):
        op.drop_column("sources", column)
