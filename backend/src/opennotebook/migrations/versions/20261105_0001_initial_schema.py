"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-05 09:44:08.078378
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import opennotebook.db

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS ltree")
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=False),
        sa.Column("target_id", sa.String(length=100), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_audit_log_at"), "audit_log", ["at"], unique=False)
    op.create_table(
        "groups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "secrets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("hint", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "group_members",
        sa.Column("group_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["group_id"], ["groups.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("group_id", "user_id"),
    )
    op.create_table(
        "nodes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Enum("project", "workspace", "notebook", name="node_kind"), nullable=False),
        sa.Column("parent_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=200), nullable=False),
        sa.Column("path", opennotebook.db.Ltree(), nullable=False),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "(kind = 'project' AND parent_id IS NULL) OR (kind <> 'project' AND parent_id IS NOT NULL)",
            name="ck_nodes_project_is_root",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["nodes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("parent_id", "slug", name="uq_nodes_parent_slug"),
    )
    op.create_index("ix_nodes_path_gist", "nodes", ["path"], unique=False, postgresql_using="gist")
    op.create_index(
        "uq_nodes_root_slug", "nodes", ["slug"], unique=True, postgresql_where=sa.text("parent_id IS NULL")
    )
    op.create_table(
        "providers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "groq",
                "openrouter",
                "gemini",
                "cloudflare",
                "cerebras",
                "mistral",
                "nvidia",
                "huggingface",
                "ollama",
                name="provider_kind",
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=True),
        sa.Column("secret_id", sa.UUID(), nullable=True),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("timeout_s", sa.Integer(), nullable=False),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["secret_id"], ["secrets.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "node_grants",
        sa.Column("node_id", sa.UUID(), nullable=False),
        sa.Column("principal_type", sa.String(length=10), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.Enum("viewer", "editor", "owner", name="grant_role"), nullable=False),
        sa.CheckConstraint("principal_type IN ('user','group')", name="ck_grants_principal"),
        sa.ForeignKeyConstraint(["node_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("node_id", "principal_type", "principal_id"),
    )
    op.create_table(
        "provider_models",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("provider_id", sa.UUID(), nullable=False),
        sa.Column("model", sa.String(length=300), nullable=False),
        sa.Column("display_name", sa.String(length=300), nullable=True),
        sa.Column(
            "capabilities",
            postgresql.ARRAY(
                sa.Enum(
                    "embedding",
                    "rerank",
                    "chat",
                    "summary",
                    "vision",
                    "ocr",
                    "graph_extraction",
                    name="model_phase",
                )
            ),
            nullable=False,
        ),
        sa.Column("capabilities_source", sa.String(length=20), nullable=False),
        sa.Column("context_window", sa.Integer(), nullable=True),
        sa.Column("embedding_dim", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["provider_id"], ["providers.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_id", "model", name="uq_provider_models"),
    )
    op.create_index(op.f("ix_provider_models_provider_id"), "provider_models", ["provider_id"], unique=False)
    op.create_table(
        "phase_assignments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "phase",
            postgresql.ENUM(
                "embedding",
                "rerank",
                "chat",
                "summary",
                "vision",
                "ocr",
                "graph_extraction",
                name="model_phase",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("project_id", sa.UUID(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("provider_model_id", sa.UUID(), nullable=False),
        sa.Column("params", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["provider_model_id"], ["provider_models.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_phase_global",
        "phase_assignments",
        ["phase", "position"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )
    op.create_index(
        "uq_phase_project",
        "phase_assignments",
        ["phase", "project_id", "position"],
        unique=True,
        postgresql_where=sa.text("project_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_phase_project", table_name="phase_assignments", postgresql_where=sa.text("project_id IS NOT NULL")
    )
    op.drop_index(
        "uq_phase_global", table_name="phase_assignments", postgresql_where=sa.text("project_id IS NULL")
    )
    op.drop_table("phase_assignments")
    op.drop_index(op.f("ix_provider_models_provider_id"), table_name="provider_models")
    op.drop_table("provider_models")
    op.drop_table("node_grants")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("providers")
    op.drop_index("uq_nodes_root_slug", table_name="nodes", postgresql_where=sa.text("parent_id IS NULL"))
    op.drop_index("ix_nodes_path_gist", table_name="nodes", postgresql_using="gist")
    op.drop_table("nodes")
    op.drop_table("group_members")
    op.drop_table("users")
    op.drop_table("secrets")
    op.drop_table("groups")
    op.drop_index(op.f("ix_audit_log_at"), table_name="audit_log")
    op.drop_table("audit_log")
    for enum_name in ("model_phase", "grant_role", "provider_kind", "node_kind"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
