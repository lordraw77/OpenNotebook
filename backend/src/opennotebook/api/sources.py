"""Sources: upload, listing, switches, re-indexing, chunks, original file, and scoped search."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi import Response as FastAPIResponse
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select

from opennotebook.acl import get_node_for, get_search_scope, visible_nodes
from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.ingestion import queue
from opennotebook.ingestion.parsers import UnsupportedContent, sniff
from opennotebook.ingestion.pipeline import blob_key, descendants, web_digest
from opennotebook.ingestion.search import search_scope
from opennotebook.ingestion.vectors import get_vector_index
from opennotebook.ingestion.web import FetchError, normalize_url
from opennotebook.models import (
    TERMINAL_STATUSES,
    Chunk,
    GrantRole,
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
    parent_source_id: uuid.UUID | None = None
    # members of an archive / pages of a crawl (set by the listing endpoint)
    child_count: int = 0
    uri: str | None = None
    language: str | None = None
    summary: str | None = None
    suggested_questions: list[str] = []
    summary_status: str | None = None
    summary_error: str | None = None
    graph_status: str | None = None
    graph_error: str | None = None
    # archive manifest, web fetch details, crawl settings
    details: dict = {}
    created_at: datetime
    indexed_at: datetime | None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _details(cls, value: object) -> object:
        if isinstance(value, Source):
            meta = value.metadata_ or {}
            details = {
                k: meta[k]
                for k in ("archive", "final_url", "content_type", "fetched_at", "crawl", "rendition")
                if k in meta
            }
            return {
                **{c: getattr(value, c) for c in cls.model_fields if c != "details" and hasattr(value, c)},
                "details": details,
            }
        return value


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
    # Sources can be added to any node (project, workspace or notebook); `notebook_id` is the container node.
    notebook, _ = await get_node_for(session, user, notebook_id, GrantRole.editor)
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
            kind=SourceKind(sniffed.kind),
            language=sniffed.language,
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


class WebIn(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=20)
    # 0 = only the given pages; 1..WEB_CRAWL_MAX_DEPTH = follow links on the same site
    crawl_depth: int = Field(default=0, ge=0)
    max_pages: int | None = Field(default=None, ge=1)


@router.post("/nodes/{notebook_id}/web", response_model=list[UploadResult], status_code=201)
async def add_web_pages(
    notebook_id: uuid.UUID, body: WebIn, user: CurrentUser, session: SessionDep
) -> list[UploadResult]:
    """Add web pages by URL; they are fetched by the worker (SSRF-protected) and indexed like documents."""
    notebook, _ = await get_node_for(session, user, notebook_id, GrantRole.editor)
    settings = get_settings()
    if body.crawl_depth > settings.web_crawl_max_depth:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"crawl_depth is limited to {settings.web_crawl_max_depth}"
        )
    max_pages = min(body.max_pages or settings.web_crawl_max_pages, settings.web_crawl_max_pages)
    results: list[UploadResult] = []
    created: list[Source] = []
    for raw in body.urls:
        try:
            url = normalize_url(raw)
        except (FetchError, ValueError) as exc:
            results.append(UploadResult(filename=raw[:300], error=str(exc)))
            continue
        digest = web_digest(url)
        existing = await session.scalar(
            select(Source).where(
                Source.notebook_id == notebook.id,
                Source.content_sha256 == digest,
                Source.deleted_at.is_(None),
            )
        )
        if existing is not None:
            results.append(
                UploadResult(filename=url, source=SourceOut.model_validate(existing), duplicate=True)
            )
            continue
        source = Source(
            id=uuid.uuid4(),
            notebook_id=notebook.id,
            kind=SourceKind.web,
            title=url[:500],
            original_path=url,
            uri=url,
            mime_type="text/html",
            content_sha256=digest,
            size_bytes=0,
            status=SourceStatus.queued,
            created_by=user.id,
            warnings=[],
            metadata_={},
        )
        if body.crawl_depth:
            source.metadata_ = {
                "crawl": {"root": str(source.id), "depth_left": body.crawl_depth, "max_pages": max_pages}
            }
        session.add(source)
        audit(session, user, "source.web", "source", source.id, url=url, crawl_depth=body.crawl_depth)
        created.append(source)
        results.append(UploadResult(filename=url, source=None))
    await session.commit()
    for source in created:
        await session.refresh(source)
        queue.enqueue_ingestion(source.id, "web")
    by_url = {s.uri: s for s in created}
    return [
        UploadResult(filename=r.filename, source=SourceOut.model_validate(by_url[r.filename]))
        if r.source is None and r.error is None and r.filename in by_url
        else r
        for r in results
    ]


class SourceCounts(BaseModel):
    # top-level sources (archive members and crawled pages excluded) directly in each node
    nodes: dict[uuid.UUID, int]
    # sources still being processed in the visible tree (drives client polling)
    processing: int


async def _readable_node_ids(session, user, scope_id: uuid.UUID | None) -> list[uuid.UUID]:  # type: ignore[no-untyped-def]
    readable = [n for n, role in await visible_nodes(session, user) if role is not None]
    if scope_id is not None:
        scope, _ = await get_node_for(session, user, scope_id)
        readable = [n for n in readable if n.path == scope.path or n.path.startswith(scope.path + ".")]
    return [n.id for n in readable]


@router.get("/sources", response_model=list[SourceOut])
async def list_sources(
    user: CurrentUser,
    session: SessionDep,
    response: FastAPIResponse,
    scope_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = Query(default=None, description="only sources directly in this node"),
    parent_id: uuid.UUID | None = Query(default=None, description="only members of this archive or crawl"),
    top_level: bool = Query(default=False, description="exclude archive members and crawled pages"),
    q: str | None = Query(default=None, max_length=200, description="title contains (case-insensitive)"),
    ids: list[uuid.UUID] | None = Query(default=None, max_length=500),
    status_filter: SourceStatus | None = Query(default=None, alias="status"),
    include_notes: bool = True,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=1000),
) -> list[Source]:
    """Sources the user can read, optionally restricted to a subtree, a node or an archive.

    Paginated with `offset`/`limit`; the total is in the `X-Total-Count` header."""
    node_ids = await _readable_node_ids(session, user, scope_id)
    if node_id is not None:
        node_ids = [n for n in node_ids if n == node_id]
    if not node_ids:
        response.headers["X-Total-Count"] = "0"
        return []
    stmt = select(Source).where(Source.notebook_id.in_(node_ids), Source.deleted_at.is_(None))
    if parent_id is not None:
        stmt = stmt.where(Source.parent_source_id == parent_id)
    elif top_level:
        stmt = stmt.where(Source.parent_source_id.is_(None))
    if q:
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(Source.title.ilike(f"%{escaped}%", escape="\\"))
    if ids:
        stmt = stmt.where(Source.id.in_(ids))
    if status_filter is not None:
        stmt = stmt.where(Source.status == status_filter)
    if not include_notes:
        stmt = stmt.where(Source.kind != SourceKind.note)
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    stmt = stmt.order_by(Source.title, Source.id).offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    sources = list((await session.scalars(stmt)).all())
    if sources:
        rows = await session.execute(
            select(Source.parent_source_id, func.count())
            .where(Source.parent_source_id.in_([s.id for s in sources]), Source.deleted_at.is_(None))
            .group_by(Source.parent_source_id)
        )
        counts: dict[uuid.UUID | None, int] = {parent: n for parent, n in rows.all()}
        for src in sources:
            src.child_count = counts.get(src.id, 0)  # type: ignore[attr-defined]
    return sources


@router.get("/sources/counts", response_model=SourceCounts)
async def source_counts(
    user: CurrentUser, session: SessionDep, scope_id: uuid.UUID | None = None
) -> SourceCounts:
    """Per-node counts that let the client build the tree without loading every source."""
    node_ids = await _readable_node_ids(session, user, scope_id)
    if not node_ids:
        return SourceCounts(nodes={}, processing=0)
    alive = (Source.notebook_id.in_(node_ids), Source.deleted_at.is_(None))
    rows = await session.execute(
        select(Source.notebook_id, func.count())
        .where(*alive, Source.parent_source_id.is_(None))
        .group_by(Source.notebook_id)
    )
    processing = await session.scalar(
        select(func.count()).where(*alive, Source.status.not_in(list(TERMINAL_STATUSES)))
    )
    nodes: dict[uuid.UUID, int] = {node: n for node, n in rows.all()}
    return SourceCounts(nodes=nodes, processing=processing or 0)


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
        # archive members and crawled pages follow their parent's switch
        for child in await descendants(session, source.id):
            child.active = body.active
    audit(session, user, "source.update", "source", source.id, **body.model_dump(exclude_unset=True))
    await session.commit()
    await session.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    source = await _source_for(session, user, source_id, GrantRole.editor)
    if source.kind == SourceKind.note:
        raise HTTPException(status.HTTP_409_CONFLICT, "Disable indexing on the note instead")
    children = await descendants(session, source.id)
    now = datetime.now(UTC)
    source.deleted_at = now
    for child in children:
        child.deleted_at = now
    audit(session, user, "source.delete", "source", source.id, title=source.title, children=len(children))
    await session.commit()
    for s in [source, *children]:
        queue.enqueue_purge(s.id)


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


@router.get("/sources/{source_id}/view")
async def view_file(source_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> Response:
    """What the viewer renders: the PDF rendition of a converted office document, otherwise the original."""
    source = await _source_for(session, user, source_id, GrantRole.viewer)
    blob = None
    if (source.metadata_ or {}).get("rendition") == "pdf":
        blob = await session.get(SourceBlob, (source.id, "pdf"))
    if blob is None:
        blob = await session.get(SourceBlob, (source.id, "original"))
    if blob is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not available")
    data = await get_blob_store().get(blob.object_key)
    return Response(
        data,
        media_type=blob.content_type,
        headers={"Content-Disposition": "inline", "Cache-Control": "private, no-store"},
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
    from opennotebook.ratelimit import too_many_attempts

    limit = get_settings().search_rate_limit_per_minute
    if limit and await too_many_attempts(f"search:{user.id}", limit, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many searches: wait a minute and retry")
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
