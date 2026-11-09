"""Which embedding index serves a project's searches, and the atomic switch after a model change (US-08).

A project's searches always use the *serving* model (`project_settings.embedding_model_id`). When the
project's embedding chain points to another model (the *target*), ingestion embeds sources with the target and
keeps them searchable in the serving index:
  - sources re-indexed for the change keep their old vectors in the serving collection;
  - sources added meanwhile are embedded with both models.
When no source is left without target vectors (nothing queued or processing, every ready source on the
target), the serving model is switched in one row update and the old vectors of the project are removed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.ingestion.vectors import VectorIndex, collection_for
from opennotebook.models import ModelPhase, Node, ProjectSettings, Source, SourceStatus
from opennotebook.providers.gateway import GatewayError, ModelGateway

log = logging.getLogger(__name__)

OPEN_STATUSES = (SourceStatus.queued, SourceStatus.parsing, SourceStatus.chunking, SourceStatus.embedding)


async def settings_row(
    session: AsyncSession, project_id: uuid.UUID, *, lock: bool = False
) -> ProjectSettings:
    row = await session.get(ProjectSettings, project_id, with_for_update=lock)
    if row is None:
        # Concurrent jobs of a new project race to create the row: insert-if-missing, then read it back.
        await session.execute(
            insert(ProjectSettings)
            .values(project_id=project_id)
            .on_conflict_do_nothing(index_elements=["project_id"])
        )
        row = await session.get_one(ProjectSettings, project_id, with_for_update=lock, populate_existing=True)
    return row


async def serving_model_id(
    session: AsyncSession, project_id: uuid.UUID, default: uuid.UUID | None = None
) -> uuid.UUID | None:
    """The model whose index answers searches; the first indexed model becomes it."""
    row = await settings_row(session, project_id)
    if row.embedding_model_id is None and default is not None:
        # atomic: of two concurrent first jobs, only one sets it, the other reads the winner's value
        await session.execute(
            update(ProjectSettings)
            .where(ProjectSettings.project_id == project_id, ProjectSettings.embedding_model_id.is_(None))
            .values(embedding_model_id=default)
        )
        await session.refresh(row)
    return row.embedding_model_id


def _project_sources(project_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return (
        select(Source)
        .join(Node, Node.id == Source.notebook_id)
        .where(Node.path.op("<@")(f"n{project_id.hex}"), Source.deleted_at.is_(None))
    )


async def index_status(session: AsyncSession, project_id: uuid.UUID) -> dict:
    """Serving vs configured model and re-indexing progress (RAG Status, project settings)."""
    row = await session.get(ProjectSettings, project_id)
    serving = row.embedding_model_id if row else None
    try:
        target = (await ModelGateway(session).resolve(ModelPhase.embedding, project_id))[0].model.id
    except GatewayError:
        target = None
    base = _project_sources(project_id).subquery()
    total = await session.scalar(select(func.count()).select_from(base))
    on_target = (
        await session.scalar(
            select(func.count())
            .select_from(base)
            .where(base.c.embedding_model_id == target, base.c.status == SourceStatus.ready)
        )
        if target
        else 0
    )
    return {
        "serving_model_id": str(serving) if serving else None,
        "configured_model_id": str(target) if target else None,
        "switch_pending": bool(serving and target and serving != target),
        "sources": int(total or 0),
        "sources_on_configured_model": int(on_target or 0),
        "switched_at": row.index_switched_at.isoformat() if row and row.index_switched_at else None,
    }


async def maybe_switch(session: AsyncSession, project_id: uuid.UUID, index: VectorIndex) -> bool:
    """Switch the serving index to the configured model when every source has been re-indexed."""
    try:
        target = (await ModelGateway(session).resolve(ModelPhase.embedding, project_id))[0].model.id
    except GatewayError:
        return False
    row = await settings_row(session, project_id, lock=True)
    old = row.embedding_model_id
    if old is None or old == target:
        await session.commit()
        return False
    sub = _project_sources(project_id).subquery()
    pending = await session.scalar(
        select(func.count())
        .select_from(sub)
        .where(
            or_(
                sub.c.status.in_(OPEN_STATUSES),
                (sub.c.status == SourceStatus.ready) & (sub.c.embedding_model_id != target),
            )
        )
    )
    if pending:
        await session.commit()
        return False
    row.embedding_model_id = target
    row.index_switched_at = datetime.now(UTC)
    for source in (await session.scalars(_project_sources(project_id))).all():
        if (source.metadata_ or {}).get("also_indexed_in"):
            source.metadata_ = {k: v for k, v in source.metadata_.items() if k != "also_indexed_in"}
    await session.commit()
    log.info("project %s: search index switched to model %s", project_id, target)
    await index.delete_project(collection_for(old), project_id)
    return True
