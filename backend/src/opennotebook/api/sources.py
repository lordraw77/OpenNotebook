"""Sources: upload, listing, switches, re-indexing, chunks, original file, and scoped search."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from opennotebook.acl import get_node_for, get_search_scope, visible_nodes
from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.ingestion import queue
from opennotebook.ingestion.parsers import UnsupportedContent, sniff
from opennotebook.ingestion.pipeline import blob_key
from opennotebook.ingestion.search import search_scope
from opennotebook.ingestion.vectors import get_vector_index
from opennotebook.models import (
    Chunk,
    GrantRole,
    NodeKind,
    Source,
    SourceBlob,
    SourceKind,
    SourceStatus,
)
from opennotebook.providers.gateway import GatewayError
from opennotebook.storage import get_blob_store

router = APIRouter(prefix="/api", tags=["sources"])

READ_CHUNK = 1024 * 1024


class SourceOut(BaseModel):
    id: uuid.UUID
    notebook_id: uuid.UUID
    kind: SourceKind
    title: str
    original_path: str | None
    mime_type: str | None
    size_bytes: int
    active: bool
    status: SourceStatus
    error: dict | None
    warnings: list[str]
    chunk_count: int
    page_count: int | None
    embedding_model_id: uuid.UUID | None
    note_id: uuid.UUID | None
    created_at: datetime
    indexed_at: datetime | None

    model_config = {"from_attributes": True}


class UploadResult(BaseModel):
    filename: str
    source: SourceOut | None = None
    duplicate: bool = False
    error: str | None = None


class SourceUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    active: bool | None = None


class ChunkOut(BaseModel):
    id: uuid.UUID
    ordinal: int
    text: str
    heading_path: list[str]
    page_start: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None
    char_start: int
    char_end: int
    token_count: int
    block_type: str

    model_config = {"from_attributes": True}


class SearchIn(BaseModel):
    scope_id: uuid.UUID
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)


class SearchHitOut(BaseModel):
    score: float
    chunk: ChunkOut
    source_id: uuid.UUID
    source_title: str
    notebook_id: uuid.UUID
    notebook_name: str


class SearchOut(BaseModel):
    embedding_model: str
    hits: list[SearchHitOut]


async def _source_for(
    session: SessionDep, user: CurrentUser, source_id: uuid.UUID, role: GrantRole
) -> Source:
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found")
    await get_node_for(session, user, source.notebook_id, role)
    return source


async def _read_limited(upload: UploadFile, limit: int) -> bytes:
    data = bytearray()
    while chunk := await upload.read(READ_CHUNK):
        data += chunk
        if len(data) > limit:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"{upload.filename}: larger than {limit // (1024 * 1024)} MB",
            )
    return bytes(data)


@router.post("/nodes/{notebook_id}/sources", response_model=list[UploadResult], status_code=201)
async def upload_sources(
    notebook_id: uuid.UUID, user: CurrentUser, session: SessionDep, files: list[UploadFile] = File(...)
) -> list[UploadResult]:
    notebook, _ = await get_node_for(session, user, notebook_id, GrantRole.editor)
    if notebook.kind != NodeKind.notebook:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Sources can only be added to a notebook")
    limit = get_settings().upload_max_mb * 1024 * 1024
    store = get_blob_store()
    results: list[UploadResult] = []
    for upload in files:
        filename = (upload.filename or "upload").replace("\\", "/").rsplit("/", 1)[-1][:300]
        data = await _read_limited(upload, limit)
        try:
            sniffed = sniff(data, filename)
        except UnsupportedContent as exc:
            results.append(UploadResult(filename=filename, error=str(exc)))
            continue
        digest = hashlib.sha256(data).digest()
        existing = await session.scalar(
            select(Source).where(
                Source.notebook_id == notebook.id,
                Source.content_sha256 == digest,
                Source.deleted_at.is_(None),
                Source.kind != SourceKind.note,
            )
        )
        if existing is not None:
            results.append(
                UploadResult(filename=filename, source=SourceOut.model_validate(existing), duplicate=True)
            )
            continue
        source = Source(
            id=uuid.uuid4(),
            notebook_id=notebook.id,
            kind=SourceKind.file,
            title=filename,
            original_path=filename,
            mime_type=sniffed.mime_type,
            content_sha256=digest,
            size_bytes=len(data),
            status=SourceStatus.queued,
            created_by=user.id,
            warnings=[],
            metadata_={"format": sniffed.format},
        )
        await store.put(blob_key(source.id, "original"), data, sniffed.mime_type)
        session.add(source)
        session.add(
            SourceBlob(
                source_id=source.id,
                role="original",
                object_key=blob_key(source.id, "original"),
                size_bytes=len(data),
                content_type=sniffed.mime_type,
            )
        )
        audit(session, user, "source.upload", "source", source.id, filename=filename, size=len(data))
        await session.commit()
        await session.refresh(source)
        queue.enqueue_ingestion(source.id, "upload")
        results.append(UploadResult(filename=filename, source=SourceOut.model_validate(source)))
    return results


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID | None = None,
    status_filter: SourceStatus | None = Query(default=None, alias="status"),
    include_notes: bool = True,
) -> list[Source]:
    """Sources the user can read, optionally restricted to a subtree."""
    readable = [
        n
        for n, role in await visible_nodes(session, user)
        if role is not None and n.kind == NodeKind.notebook
    ]
    if scope_id is not None:
        scope, _ = await get_node_for(session, user, scope_id)
        readable = [n for n in readable if n.path == scope.path or n.path.startswith(scope.path + ".")]
    if not readable:
        return []
    stmt = (
        select(Source)
        .where(Source.notebook_id.in_([n.id for n in readable]), Source.deleted_at.is_(None))
        .order_by(Source.title)
    )
    if status_filter is not None:
        stmt = stmt.where(Source.status == status_filter)
    if not include_notes:
        stmt = stmt.where(Source.kind != SourceKind.note)
    return list((await session.scalars(stmt)).all())


@router.get("/sources/{source_id}", response_model=SourceOut)
async def get_source(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Source:
    return await _source_for(session, user, source_id, GrantRole.viewer)


@router.patch("/sources/{source_id}", response_model=SourceOut)
async def update_source(
    source_id: uuid.UUID, body: SourceUpdate, user: CurrentUser, session: SessionDep
) -> Source:
    source = await _source_for(session, user, source_id, GrantRole.editor)
    if body.title is not None:
        source.title = body.title.strip()
    if body.active is not None:
        source.active = body.active
    audit(session, user, "source.update", "source", source.id, **body.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    source = await _source_for(session, user, source_id, GrantRole.editor)
    if source.kind == SourceKind.note:
        raise HTTPException(status.HTTP_409_CONFLICT, "Disable indexing on the note instead")
    source.deleted_at = datetime.now(UTC)
    audit(session, user, "source.delete", "source", source.id, title=source.title)
    await session.commit()
    queue.enqueue_purge(source.id)


@router.post("/sources/{source_id}/reindex", response_model=SourceOut)
async def reindex_source(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Source:
    source = await _source_for(session, user, source_id, GrantRole.editor)
    if source.status not in (SourceStatus.ready, SourceStatus.failed):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ingestion already in progress")
    source.status = SourceStatus.queued
    source.error = None
    await session.commit()
    await session.refresh(source)
    queue.enqueue_ingestion(source.id, "reindex")
    return source


@router.get("/sources/{source_id}/chunks", response_model=list[ChunkOut])
async def list_chunks(
    source_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[Chunk]:
    source = await _source_for(session, user, source_id, GrantRole.viewer)
    stmt = (
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.ordinal).offset(offset).limit(limit)
    )
    return list((await session.scalars(stmt)).all())


@router.get("/sources/{source_id}/file")
async def download_original(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    source = await _source_for(session, user, source_id, GrantRole.viewer)
    blob = await session.get(SourceBlob, (source.id, "original"))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Original file not available")
    data = await get_blob_store().get(blob.object_key)
    safe_name = "".join(ch for ch in source.title if ch.isalnum() or ch in "._- ")[:200] or "source"
    return Response(
        data,
        media_type=blob.content_type,
        headers={
            "Content-Disposition": f'attachment; filename="{safe_name}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/sources/{source_id}/text")
async def extracted_text(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    """Normalized text the chunk character offsets refer to (used to highlight cited passages)."""
    source = await _source_for(session, user, source_id, GrantRole.viewer)
    blob = await session.get(SourceBlob, (source.id, "text"))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Text not extracted yet")
    data = await get_blob_store().get(blob.object_key)
    return Response(
        data,
        media_type="text/plain; charset=utf-8",
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/search", response_model=SearchOut)
async def search(body: SearchIn, user: CurrentUser, session: SessionDep) -> SearchOut:
    scope = await get_search_scope(session, user, body.scope_id)
    try:
        hits, model_label = await search_scope(
            session, get_vector_index(), user, scope, body.query, body.limit
        )
    except GatewayError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Embedding failed: {exc.describe()}"
        ) from exc
    return SearchOut(
        embedding_model=model_label,
        hits=[
            SearchHitOut(
                score=h.score,
                chunk=ChunkOut.model_validate(h.chunk),
                source_id=h.source.id,
                source_title=h.source.title,
                notebook_id=h.notebook.id,
                notebook_name=h.notebook.name,
            )
            for h in hits
        ],
    )


async def chunk_totals(session: SessionDep, notebook_ids: list[uuid.UUID]) -> tuple[int, int]:
    row = (
        await session.execute(
            select(func.count(Source.id), func.coalesce(func.sum(Source.chunk_count), 0)).where(
                Source.notebook_id.in_(notebook_ids), Source.deleted_at.is_(None)
            )
        )
    ).one()
    return int(row[0]), int(row[1])
