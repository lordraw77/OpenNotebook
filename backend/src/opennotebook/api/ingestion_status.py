"""Ingestion overview for the RAG Status page, restricted to what the user can read."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from opennotebook.acl import visible_nodes
from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep
from opennotebook.ingestion.pipeline import node_ids_from_path
from opennotebook.models import (
    IngestionJob,
    NodeKind,
    PhaseAssignment,
    Provider,
    ProviderModel,
    Source,
    SourceStatus,
)
from opennotebook.worker import QUEUES

router = APIRouter(prefix="/api/ingestion", tags=["ingestion"])


class FailedSource(BaseModel):
    id: uuid.UUID
    title: str
    notebook_id: uuid.UUID
    error: dict | None
    updated_at: datetime


class ProjectIndex(BaseModel):
    project_id: uuid.UUID
    project_name: str
    embedding_model: str | None
    embedding_source: str  # project | global | none
    sources: int
    chunks: int
    stale_sources: int  # indexed with a model different from the current one
    # the model whose index answers searches; differs from embedding_model until a re-index completes
    serving_model: str | None = None
    switch_pending: bool = False


class RecentJob(BaseModel):
    source_id: uuid.UUID
    reason: str
    status: str
    attempts: int
    provider_model: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class IngestionStatus(BaseModel):
    by_status: dict[str, int]
    queues: dict[str, int] | None
    failed: list[FailedSource]
    projects: list[ProjectIndex]
    recent_jobs: list[RecentJob]


async def _queue_lengths() -> dict[str, int] | None:
    from redis.asyncio import from_url
    from redis.exceptions import RedisError

    client = from_url(get_settings().redis_url_with_auth, socket_timeout=2, socket_connect_timeout=2)
    try:
        return {q: int(await client.llen(q)) for q in QUEUES}
    except (RedisError, OSError):
        return None
    finally:
        await client.aclose()


async def _embedding_model(
    session: SessionDep, project_id: uuid.UUID
) -> tuple[uuid.UUID | None, str | None, str]:
    for pid, label in ((project_id, "project"), (None, "global")):
        stmt = (
            select(ProviderModel.id, Provider.name, ProviderModel.model)
            .join(PhaseAssignment, PhaseAssignment.provider_model_id == ProviderModel.id)
            .join(Provider, Provider.id == ProviderModel.provider_id)
            .where(PhaseAssignment.phase == "embedding", PhaseAssignment.position == 0)
        )
        stmt = stmt.where(
            PhaseAssignment.project_id.is_(None) if pid is None else PhaseAssignment.project_id == pid
        )
        row = (await session.execute(stmt)).first()
        if row:
            return row[0], f"{row[1]}/{row[2]}", label
    return None, None, "none"


@router.get("/status", response_model=IngestionStatus)
async def ingestion_status(user: CurrentUser, session: SessionDep) -> IngestionStatus:
    nodes = [(n, r) for n, r in await visible_nodes(session, user) if r is not None]
    notebooks = [n for n, _ in nodes if n.kind == NodeKind.notebook]
    nb_ids = [n.id for n in notebooks]
    base = (Source.notebook_id.in_(nb_ids), Source.deleted_at.is_(None))

    by_status = {s.value: 0 for s in SourceStatus}
    if nb_ids:
        for st, count in (
            await session.execute(select(Source.status, func.count()).where(*base).group_by(Source.status))
        ).all():
            by_status[st.value] = count

    failed = []
    if nb_ids:
        failed_rows = (
            await session.scalars(
                select(Source)
                .where(*base, Source.status == SourceStatus.failed)
                .order_by(Source.updated_at.desc())
                .limit(20)
            )
        ).all()
        failed = [
            FailedSource(
                id=s.id, title=s.title, notebook_id=s.notebook_id, error=s.error, updated_at=s.updated_at
            )
            for s in failed_rows
        ]

    projects: list[ProjectIndex] = []
    for project, _ in [(n, r) for n, r in nodes if n.kind == NodeKind.project]:
        p_nbs = [n.id for n in notebooks if node_ids_from_path(n.path)[0] == str(project.id)]
        model_id, label, source = await _embedding_model(session, project.id)
        count = chunks = stale = 0
        if p_nbs:
            row = (
                await session.execute(
                    select(func.count(), func.coalesce(func.sum(Source.chunk_count), 0)).where(
                        Source.notebook_id.in_(p_nbs), Source.deleted_at.is_(None)
                    )
                )
            ).one()
            count, chunks = int(row[0]), int(row[1])
            if model_id is not None:
                stale = int(
                    await session.scalar(
                        select(func.count()).where(
                            Source.notebook_id.in_(p_nbs),
                            Source.deleted_at.is_(None),
                            Source.status == SourceStatus.ready,
                            Source.embedding_model_id != model_id,
                        )
                    )
                    or 0
                )
        from opennotebook.models import ProjectSettings, Provider, ProviderModel

        settings_row = await session.get(ProjectSettings, project.id)
        serving = None
        if settings_row is not None and settings_row.embedding_model_id is not None:
            m = await session.get(ProviderModel, settings_row.embedding_model_id)
            prov = await session.get(Provider, m.provider_id) if m else None
            serving = f"{prov.name}/{m.model}" if m and prov else None
        projects.append(
            ProjectIndex(
                project_id=project.id,
                project_name=project.name,
                embedding_model=label,
                embedding_source=source,
                sources=count,
                chunks=chunks,
                stale_sources=stale,
                serving_model=serving or label,
                switch_pending=bool(
                    settings_row
                    and settings_row.embedding_model_id
                    and model_id
                    and settings_row.embedding_model_id != model_id
                ),
            )
        )

    jobs = []
    if nb_ids:
        job_rows = (
            await session.scalars(
                select(IngestionJob)
                .join(Source, Source.id == IngestionJob.source_id)
                .where(Source.notebook_id.in_(nb_ids))
                .order_by(IngestionJob.created_at.desc())
                .limit(20)
            )
        ).all()
        jobs = [
            RecentJob(
                source_id=j.source_id,
                reason=j.reason,
                status=j.status,
                attempts=j.attempts,
                provider_model=j.provider_model,
                error=j.error,
                created_at=j.created_at,
                finished_at=j.finished_at,
            )
            for j in job_rows
        ]

    return IngestionStatus(
        by_status=by_status,
        queues=await _queue_lengths(),
        failed=failed,
        projects=projects,
        recent_jobs=jobs,
    )


@router.post("/projects/{project_id}/reindex")
async def reindex_project(project_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict:
    """Re-index every ready or failed source of a project, e.g. after changing its embedding model.

    Requires the owner role on the project.
    """
    from opennotebook.acl import get_node_for
    from opennotebook.ingestion import queue
    from opennotebook.models import GrantRole, Node

    project, _ = await get_node_for(session, user, project_id, GrantRole.owner)
    ids = (
        await session.scalars(
            select(Source.id)
            .join(Node, Node.id == Source.notebook_id)
            .where(
                Node.path.op("<@")(project.path),
                Source.deleted_at.is_(None),
                Source.status.in_([SourceStatus.ready, SourceStatus.failed]),
            )
        )
    ).all()
    for sid in ids:
        src = await session.get(Source, sid)
        if src is not None:
            src.status = SourceStatus.queued
            src.error = None
    await session.commit()
    for sid in ids:
        queue.enqueue_ingestion(sid, "reindex")
    return {"queued": len(ids)}


@router.post("/projects/{project_id}/graph")
async def rebuild_project_graph(project_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> dict:
    """Re-extract the knowledge graph of every ready source (no re-embedding), e.g. after configuring or
    changing the graph extraction model. Requires the owner role on the project."""
    from opennotebook.acl import get_node_for
    from opennotebook.graph.extract import wants_graph
    from opennotebook.ingestion import queue
    from opennotebook.models import GrantRole, Node

    project, _ = await get_node_for(session, user, project_id, GrantRole.owner)
    sources = (
        await session.scalars(
            select(Source)
            .join(Node, Node.id == Source.notebook_id)
            .where(
                Node.path.op("<@")(project.path),
                Source.deleted_at.is_(None),
                Source.status == SourceStatus.ready,
            )
        )
    ).all()
    queued = [s for s in sources if wants_graph(s)]
    for s in queued:
        s.graph_status = "pending"
        s.graph_error = None
    await session.commit()
    for s in queued:
        queue.enqueue_graph(s.id)
    return {"queued": len(queued)}
