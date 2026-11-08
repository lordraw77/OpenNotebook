"""ORM models: identity, hierarchy, permissions, model providers, audit (M0); sources, chunks, notes (M1)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
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
    # `sub` claim of the identity provider (OIDC sign-in); NULL for local-only accounts
    oidc_subject: Mapped[str | None] = mapped_column(String(255), unique=True)


class Group(TimestampMixin, Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    # local | oidc (members synchronized from the identity provider at sign-in)
    source: Mapped[str] = mapped_column(String(20), default="local", server_default="local")


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


class SourceKind(enum.StrEnum):
    file = "file"
    code = "code"
    image = "image"
    web = "web"
    note = "note"
    archive = "archive"


class SourceStatus(enum.StrEnum):
    queued = "queued"
    parsing = "parsing"
    chunking = "chunking"
    embedding = "embedding"
    ready = "ready"
    failed = "failed"


TERMINAL_STATUSES = {SourceStatus.ready, SourceStatus.failed}


class Note(TimestampMixin, Base):
    """User note in a notebook. When `indexed`, a source of kind `note` mirrors it in the index."""

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    notebook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    body_md: Mapped[str] = mapped_column(Text, default="")
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # manual | chat
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    indexed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        Index(
            "uq_sources_notebook_hash",
            "notebook_id",
            "content_sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND kind <> 'note'"),
        ),
        Index("ix_sources_status_open", "status", postgresql_where=text("status NOT IN ('ready','failed')")),
        Index(
            "ix_sources_parent_source_id",
            "parent_source_id",
            postgresql_where=text("parent_source_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    notebook_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    parent_source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    note_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), unique=True
    )
    kind: Mapped[SourceKind] = mapped_column(_enum(SourceKind, "source_kind"))
    title: Mapped[str] = mapped_column(String(500))
    original_path: Mapped[str | None] = mapped_column(Text)
    uri: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(200))
    language: Mapped[str | None] = mapped_column(String(50))
    content_sha256: Mapped[bytes] = mapped_column(LargeBinary)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[SourceStatus] = mapped_column(
        _enum(SourceStatus, "source_status"), default=SourceStatus.queued
    )
    error: Mapped[dict | None] = mapped_column(JSONB)
    warnings: Mapped[list] = mapped_column(JSONB, default=list)
    pipeline_version: Mapped[str | None] = mapped_column(String(20))
    embedding_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_models.id", ondelete="SET NULL")
    )
    vector_collection: Mapped[str | None] = mapped_column(String(200))
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int | None] = mapped_column(Integer)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Summary and suggested questions, generated after indexing (the source is usable meanwhile).
    # summary_status: pending | done | failed | skipped (NULL = not applicable, e.g. archive members)
    summary: Mapped[str | None] = mapped_column(Text)
    suggested_questions: Mapped[list] = mapped_column(JSONB, default=list)
    summary_status: Mapped[str | None] = mapped_column(String(20))
    summary_model: Mapped[str | None] = mapped_column(String(400))
    summary_error: Mapped[str | None] = mapped_column(Text)
    # Knowledge graph extraction: pending | done | failed | skipped
    graph_status: Mapped[str | None] = mapped_column(String(20))
    graph_model: Mapped[str | None] = mapped_column(String(400))
    graph_error: Mapped[str | None] = mapped_column(Text)


class SourceBlob(Base):
    __tablename__ = "source_blobs"

    source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(30), primary_key=True)  # original | text
    object_key: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    content_type: Mapped[str] = mapped_column(String(200))


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("source_id", "ordinal", name="uq_chunks_source_ordinal"),
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    heading_path: Mapped[list[str]] = mapped_column(ARRAY(Text), default=list)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    bboxes: Mapped[list | None] = mapped_column(JSONB)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int] = mapped_column(Integer)
    block_type: Mapped[str] = mapped_column(String(30), default="text")
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('simple', text)", persisted=True), nullable=True)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    reason: Mapped[str] = mapped_column(String(30), default="upload")  # upload | reindex | retry | note
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | running | succeeded | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_model: Mapped[str | None] = mapped_column(String(400))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(TimestampMixin, Base):
    """A chat thread of one user, bound to a scope node (project, workspace or notebook)."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    scope_node_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300), default="New chat")


class Message(Base):
    """One turn of a conversation.

    Assistant messages keep the passages given to the model (`context`, numbered S1..Sn) and the validated
    citations actually used, so citations stay resolvable even if a source is later re-indexed or deleted.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    # complete | error | stopped
    status: Mapped[str] = mapped_column(String(20), default="complete")
    context: Mapped[list] = mapped_column(JSONB, default=list)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    # e.g. {"abstained": true, "uncited_sentences": 1, "invalid_citations": ["S12"]}
    checks: Mapped[dict] = mapped_column(JSONB, default=dict)
    provider_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_models.id", ondelete="SET NULL")
    )
    model_label: Mapped[str | None] = mapped_column(String(400))
    attempts: Mapped[list] = mapped_column(JSONB, default=list)
    usage: Mapped[dict | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Entity(TimestampMixin, Base):
    """A named thing in a project's knowledge graph, deduplicated by its canonical name.

    Entities hold no text of their own: names come from mentions, and descriptions live on each mention, so
    what a user sees is always derived from the chunks they are allowed to read (threat T1).
    """

    __tablename__ = "entities"
    __table_args__ = (UniqueConstraint("project_id", "canonical", name="uq_entities_project_canonical"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    canonical: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(300))
    type: Mapped[str] = mapped_column(String(40), default="concept")


class EntityMention(Base):
    __tablename__ = "entity_mentions"

    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    # surface form and what this passage says about the entity
    name: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text)


class Relation(Base):
    __tablename__ = "relations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), index=True)
    src_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    dst_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    # the passage that states the relation; visibility follows its source
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chunks.id", ondelete="CASCADE"))
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)


class WikiPage(Base):
    """Generated wiki text for an entity, cached per set of visible sources (`basis`).

    Two users who can read the same sources share the page; anyone else gets a page generated from what they
    can read.
    """

    __tablename__ = "wiki_pages"
    __table_args__ = (UniqueConstraint("entity_id", "basis", name="uq_wiki_entity_basis"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    entity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), index=True)
    basis: Mapped[str] = mapped_column(String(64))  # sha256 of the sorted chunk ids used
    body_md: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    model_label: Mapped[str | None] = mapped_column(String(400))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ProjectSettings(Base):
    """Per-project settings that are not model chains.

    - `allowed_provider_ids`: provider policy (threat T9). NULL = every enabled provider; otherwise model
      calls for this project only go to these providers (e.g. "LAN only": the Ollama provider).
    - `embedding_model_id`: the embedding model whose index *serves* searches. When the project's embedding
      chain changes, searches keep using this index while sources are re-indexed with the new model; it is
      switched atomically once every source has vectors from the new model (US-08).
    """

    __tablename__ = "project_settings"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), primary_key=True
    )
    allowed_provider_ids: Mapped[list | None] = mapped_column(JSONB)
    embedding_model_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("provider_models.id", ondelete="SET NULL")
    )
    index_switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
