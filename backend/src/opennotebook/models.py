"""ORM models (milestone M0: identity, hierarchy, permissions, model providers, audit)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from opennotebook.db import Base, Ltree


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class NodeKind(enum.StrEnum):
    project = "project"
    workspace = "workspace"
    notebook = "notebook"


class GrantRole(enum.StrEnum):
    viewer = "viewer"
    editor = "editor"
    owner = "owner"


ROLE_RANK = {GrantRole.viewer: 1, GrantRole.editor: 2, GrantRole.owner: 3}


class ProviderKind(enum.StrEnum):
    groq = "groq"
    openrouter = "openrouter"
    gemini = "gemini"
    cloudflare = "cloudflare"
    cerebras = "cerebras"
    mistral = "mistral"
    nvidia = "nvidia"
    huggingface = "huggingface"
    ollama = "ollama"


class ModelPhase(enum.StrEnum):
    embedding = "embedding"
    rerank = "rerank"
    chat = "chat"
    summary = "summary"
    vision = "vision"
    ocr = "ocr"
    graph_extraction = "graph_extraction"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(e, name=name, values_callable=lambda x: [m.value for m in x])


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    display_name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str | None] = mapped_column(Text)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Node(TimestampMixin, Base):
    """Project / workspace / notebook. Free nesting below the project root."""

    __tablename__ = "nodes"
    __table_args__ = (
        UniqueConstraint("parent_id", "slug", name="uq_nodes_parent_slug"),
        CheckConstraint(
            "(kind = 'project' AND parent_id IS NULL) OR (kind <> 'project' AND parent_id IS NOT NULL)",
            name="ck_nodes_project_is_root",
        ),
        Index("ix_nodes_path_gist", "path", postgresql_using="gist"),
        Index("uq_nodes_root_slug", "slug", unique=True, postgresql_where=text("parent_id IS NULL")),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[NodeKind] = mapped_column(_enum(NodeKind, "node_kind"))
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nodes.id", ondelete="RESTRICT"))
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200))
    path: Mapped[str] = mapped_column(Ltree())
    depth: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NodeGrant(Base):
    __tablename__ = "node_grants"
    __table_args__ = (CheckConstraint("principal_type IN ('user','group')", name="ck_grants_principal"),)

    node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True)
    principal_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    role: Mapped[GrantRole] = mapped_column(_enum(GrantRole, "grant_role"))


class Secret(Base):
    __tablename__ = "secrets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    hint: Mapped[str] = mapped_column(String(16), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    kind: Mapped[ProviderKind] = mapped_column(_enum(ProviderKind, "provider_kind"))
    name: Mapped[str] = mapped_column(String(100), unique=True)
    base_url: Mapped[str | None] = mapped_column(Text)
    secret_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("secrets.id", ondelete="SET NULL"))
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    timeout_s: Mapped[int] = mapped_column(Integer, default=60)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ProviderModel(TimestampMixin, Base):
    __tablename__ = "provider_models"
    __table_args__ = (UniqueConstraint("provider_id", "model", name="uq_provider_models"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    provider_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("providers.id", ondelete="CASCADE"), index=True)
    model: Mapped[str] = mapped_column(String(300))
    display_name: Mapped[str | None] = mapped_column(String(300))
    capabilities: Mapped[list[ModelPhase]] = mapped_column(
        ARRAY(_enum(ModelPhase, "model_phase")), default=list
    )
    capabilities_source: Mapped[str] = mapped_column(
        String(20), default="inferred"
    )  # inferred | provider | manual
    context_window: Mapped[int | None] = mapped_column(Integer)
    embedding_dim: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True)  # still listed by the provider


class PhaseAssignment(Base):
    """Ordered model chain per phase. project_id NULL = global default, else a per-project override."""

    __tablename__ = "phase_assignments"
    __table_args__ = (
        Index(
            "uq_phase_global",
            "phase",
            "position",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        Index(
            "uq_phase_project",
            "phase",
            "project_id",
            "position",
            unique=True,
            postgresql_where=text("project_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    phase: Mapped[ModelPhase] = mapped_column(_enum(ModelPhase, "model_phase"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer)
    provider_model_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("provider_models.id", ondelete="CASCADE"))
    params: Mapped[dict] = mapped_column(JSONB, default=dict)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
