"""Ingestion and maintenance operations, independent from Celery so they can be tested directly.

Error handling:
  - UnsupportedContent / ParseError -> source `failed`, not retried;
  - GatewayError (provider down, rate limited, no model configured) -> RetryableError, retried with backoff by
    the worker; the source keeps its current status and the last error;
  - anything else -> source `failed` with the error class name.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.ingestion import PIPELINE_VERSION, queue
from opennotebook.ingestion.archives import ArchiveRejected, Limits, Member, iter_members
from opennotebook.ingestion.chunker import chunk_document, embedding_text
from opennotebook.ingestion.document import DocumentBuilder, ParsedDocument
from opennotebook.ingestion.parsers import (
    ParseError,
    UnsupportedContent,
    decode_text,
    ensure_content,
    parse,
    parse_html,
    parse_markdown,
    parse_pdf,
    parse_text,
    sniff,
)
from opennotebook.ingestion.sparse import document_vector
from opennotebook.ingestion.vectors import PointData, VectorIndex, collection_for
from opennotebook.ingestion.web import TransientFetchError, fetch, robots_allows, same_host_links
from opennotebook.models import (
    Chunk,
    IngestionJob,
    ModelPhase,
    Node,
    Source,
    SourceBlob,
    SourceKind,
    SourceStatus,
)
from opennotebook.providers.gateway import GatewayError, ModelGateway
from opennotebook.storage import BlobStore

log = logging.getLogger(__name__)


class RetryableError(Exception):
    pass


def node_ids_from_path(path: str) -> list[str]:
    """ltree labels are `n<uuid hex>`; returns the canonical uuid strings from root to leaf."""
    return [str(uuid.UUID(hex=label[1:])) for label in path.split(".")]


_CHUNK_NS = uuid.UUID("6f1c2d3e-8a4b-4c5d-9e6f-0a1b2c3d4e5f")


def chunk_uuid(source_id: uuid.UUID, ordinal: int, text: str) -> uuid.UUID:
    """Deterministic chunk id: re-indexing unchanged content keeps ids (and citations, vectors) valid."""
    digest = hashlib.sha256(text.encode()).hexdigest()
    return uuid.uuid5(_CHUNK_NS, f"{source_id}:{ordinal}:{digest}")


async def _embed_all(
    gateway: ModelGateway, texts: list[str], project_id: uuid.UUID, model_id: uuid.UUID
) -> list[list[float]]:
    batch = max(1, get_settings().embed_batch_size)
    vectors: list[list[float]] = []
    for i in range(0, len(texts), batch):
        result = await gateway.embed(
            texts[i : i + batch], project_id, input_type="passage", model_id=model_id
        )
        vectors.extend(result.value)
    if len(vectors) != len(texts):
        raise GatewayError(f"Embedding provider returned {len(vectors)} vectors for {len(texts)} chunks")
    return vectors


def blob_key(source_id: uuid.UUID, role: str) -> str:
    return f"sources/{source_id}/{role}"


async def _set_status(session: AsyncSession, source: Source, status: SourceStatus) -> None:
    source.status = status
    await session.commit()


async def ingest_source(
    session: AsyncSession,
    source_id: uuid.UUID,
    *,
    store: BlobStore,
    index: VectorIndex,
    reason: str = "upload",
    attempt: int = 1,
) -> SourceStatus:
    settings = get_settings()
    source = await session.get(Source, source_id)
    if source is None or source.deleted_at is not None:
        return SourceStatus.failed
    notebook = await session.get(Node, source.notebook_id)
    if notebook is None or notebook.deleted_at is not None:
        return SourceStatus.failed
    ancestors = node_ids_from_path(notebook.path)
    project_id = uuid.UUID(ancestors[0])

    job = IngestionJob(source_id=source.id, reason=reason, status="running", attempts=attempt)
    job.started_at = datetime.now(UTC)
    session.add(job)
    source.error = None
    await _set_status(session, source, SourceStatus.parsing)
    # Plain ids: ORM objects expire on rollback and must not be lazily reloaded in the error paths.
    job_id = job.id

    try:
        gateway = ModelGateway(session)
        doc = await _parse_source(session, source, store, gateway, project_id, job)
        text = doc.text
        await store.put(blob_key(source.id, "text"), text.encode(), "text/plain; charset=utf-8")
        await session.merge(
            SourceBlob(
                source_id=source.id,
                role="text",
                object_key=blob_key(source.id, "text"),
                size_bytes=len(text.encode()),
                content_type="text/plain; charset=utf-8",
            )
        )
        source.page_count = doc.page_count
        source.warnings = doc.warnings
        if doc.language:
            source.language = doc.language
        source.metadata_ = {
            **(source.metadata_ or {}),
            "page_sizes": doc.page_sizes,
            "detected_title": doc.title,
        }

        await _set_status(session, source, SourceStatus.chunking)
        chunks = chunk_document(doc, settings.chunk_size_tokens, settings.chunk_overlap_tokens)
        old_chunk_ids = set(
            (await session.scalars(select(Chunk.id).where(Chunk.source_id == source.id))).all()
        )
        await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
        rows = [
            Chunk(
                id=chunk_uuid(source.id, c.ordinal, c.text),
                source_id=source.id,
                ordinal=c.ordinal,
                text=c.text,
                heading_path=c.heading_path,
                page_start=c.page_start,
                page_end=c.page_end,
                bboxes=c.bboxes or None,
                char_start=c.char_start,
                char_end=c.char_end,
                line_start=c.line_start,
                line_end=c.line_end,
                token_count=c.token_count,
                block_type=c.block_type,
            )
            for c in chunks
        ]
        session.add_all(rows)
        await _set_status(session, source, SourceStatus.embedding)

        chain = await gateway.resolve(ModelPhase.embedding, project_id)
        model = chain[0].model
        collection = collection_for(model.id)
        job.provider_model = ", ".join([*(job.provider_model or "").split(", "), chain[0].label]).strip(", ")
        title = source.title
        texts = [embedding_text(title, c) for c in chunks]
        vectors = await _embed_all(gateway, texts, project_id, model.id)
        payload_base = {
            "source_id": str(source.id),
            "notebook_id": str(notebook.id),
            "project_id": str(project_id),
            "ancestors": ancestors,
        }
        points = [
            PointData(
                chunk_id=row.id,
                dense=vec,
                sparse=document_vector(text),
                payload={**payload_base, "chunk_id": str(row.id), "page": c.page_start},
            )
            for row, c, vec, text in zip(rows, chunks, vectors, texts, strict=True)
        ]

        # US-08: while the project's searches are served by another model's index, keep the source
        # searchable there: unchanged chunks (same deterministic ids) keep their old vectors; otherwise the
        # source is embedded with the serving model too.
        from opennotebook.ingestion import index_state

        serving_id = await index_state.serving_model_id(session, project_id, default=model.id)
        serving_collection = collection_for(serving_id) if serving_id else collection
        also_indexed: str | None = None
        if serving_collection != collection:
            in_serving = serving_collection in {
                source.vector_collection,
                (source.metadata_ or {}).get("also_indexed_in"),
            }
            unchanged = in_serving and {r.id for r in rows} == old_chunk_ids
            if not unchanged:
                try:
                    serving_vectors = await _embed_all(gateway, texts, project_id, serving_id)
                except GatewayError as exc:
                    source.warnings = [
                        *source.warnings,
                        f"Not searchable until the index switch completes: {exc.describe()}"[:300],
                    ]
                else:
                    await index.ensure_collection(serving_collection, len(serving_vectors[0]))
                    await index.delete_source(serving_collection, source.id)
                    await index.upsert(
                        serving_collection,
                        [
                            PointData(chunk_id=p.chunk_id, dense=v, sparse=p.sparse, payload=p.payload)
                            for p, v in zip(points, serving_vectors, strict=True)
                        ],
                    )
            also_indexed = serving_collection

        await index.ensure_collection(collection, len(vectors[0]))
        for stale in {source.vector_collection, (source.metadata_ or {}).get("also_indexed_in")} - {
            None,
            collection,
            serving_collection,
        }:
            await index.delete_source(stale, source.id)
        await index.delete_source(collection, source.id)
        await index.upsert(collection, points)
        meta = {k: v for k, v in (source.metadata_ or {}).items() if k != "also_indexed_in"}
        source.metadata_ = {**meta, "also_indexed_in": also_indexed} if also_indexed else meta
        if model.embedding_dim != len(vectors[0]):
            model.embedding_dim = len(vectors[0])

        source.embedding_model_id = model.id
        source.vector_collection = collection
        source.chunk_count = len(rows)
        source.pipeline_version = PIPELINE_VERSION
        source.indexed_at = datetime.now(UTC)
        source.status = SourceStatus.ready
        job.status = "succeeded"
        job.finished_at = datetime.now(UTC)
        from opennotebook.graph.extract import wants_graph
        from opennotebook.ingestion.summary import wants_summary

        summarize = wants_summary(source)
        if summarize:
            source.summary_status = "pending"
        graph = wants_graph(source)
        if graph:
            source.graph_status = "pending"
        await session.commit()
        if summarize:
            queue.enqueue_summary(source.id)
        if graph:
            queue.enqueue_graph(source.id)
        await _try_switch(session, project_id, index)
        return SourceStatus.ready

    except TransientFetchError as exc:
        await session.rollback()
        source = await session.get(Source, source_id)
        job_row = await session.get(IngestionJob, job_id)
        if source is not None:
            source.error = {"code": "fetch_error", "message": str(exc)[:1000], "attempt": attempt}
        if job_row is not None:
            job_row.status = "failed"
            job_row.error = str(exc)[:2000]
            job_row.finished_at = datetime.now(UTC)
        await session.commit()
        raise RetryableError(str(exc)) from exc
    except (UnsupportedContent, ParseError) as exc:
        await _fail(session, source_id, job_id, "parse_error", str(exc))
        await _try_switch(session, project_id, index)
        return SourceStatus.failed
    except GatewayError as exc:
        detail = exc.describe()
        await session.rollback()
        source = await session.get(Source, source_id)
        job_row = await session.get(IngestionJob, job_id)
        if source is not None:
            source.error = {"code": "provider_error", "message": detail[:1000], "attempt": attempt}
        if job_row is not None:
            job_row.status = "failed"
            job_row.error = detail[:2000]
            job_row.finished_at = datetime.now(UTC)
        await session.commit()
        raise RetryableError(detail) from exc
    except Exception as exc:
        log.exception("ingestion failed for source %s", source_id)
        await _fail(session, source_id, job_id, "internal_error", exc.__class__.__name__)
        return SourceStatus.failed


async def _try_switch(session: AsyncSession, project_id: uuid.UUID, index: VectorIndex) -> None:
    """A failed or deleted source may have been the last one blocking an index switch."""
    from opennotebook.ingestion import index_state

    try:
        await index_state.maybe_switch(session, project_id, index)
    except Exception:  # noqa: BLE001 - never turn a finished job into an error
        await session.rollback()
        log.exception("index switch check failed for project %s", project_id)


async def _fail(
    session: AsyncSession, source_id: uuid.UUID, job_id: uuid.UUID, code: str, message: str
) -> None:
    await session.rollback()
    source = await session.get(Source, source_id)
    job_row = await session.get(IngestionJob, job_id)
    if source is not None:
        source.status = SourceStatus.failed
        source.error = {"code": code, "message": message[:1000]}
    if job_row is not None:
        job_row.status = "failed"
        job_row.error = message[:2000]
        job_row.finished_at = datetime.now(UTC)
    await session.commit()


async def mark_failed_after_retries(session: AsyncSession, source_id: uuid.UUID, message: str) -> None:
    source = await session.get(Source, source_id)
    if source is not None:
        source.status = SourceStatus.failed
        source.error = {"code": "provider_error", "message": message[:1000], "final": True}
        await session.commit()


async def purge_source(
    session: AsyncSession, source_id: uuid.UUID, *, store: BlobStore, index: VectorIndex
) -> None:
    """Remove vectors, chunks and blobs of a (soft-deleted) source."""
    source = await session.get(Source, source_id)
    if source is None:
        return
    for name in {source.vector_collection, (source.metadata_ or {}).get("also_indexed_in")} - {None}:
        await index.delete_source(name, source.id)
    for blob in (await session.scalars(select(SourceBlob).where(SourceBlob.source_id == source.id))).all():
        await store.delete(blob.object_key)
    await session.execute(delete(SourceBlob).where(SourceBlob.source_id == source.id))
    from opennotebook.graph.store import clear_source, drop_orphans

    await clear_source(session, source.id)
    await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
    source.chunk_count = 0
    source.vector_collection = None
    notebook = await session.get(Node, source.notebook_id)
    if notebook is not None:
        await drop_orphans(session, uuid.UUID(node_ids_from_path(notebook.path)[0]))
    await session.commit()
    if notebook is not None:
        await _try_switch(session, uuid.UUID(node_ids_from_path(notebook.path)[0]), index)


async def refresh_ancestors(session: AsyncSession, node_id: uuid.UUID, *, index: VectorIndex) -> int:
    """After a move, rewrite the `ancestors` payload of every source below the node."""
    node = await session.get(Node, node_id)
    if node is None:
        return 0
    rows = (
        await session.execute(
            select(Source, Node)
            .join(Node, Node.id == Source.notebook_id)
            .where(Node.path.op("<@")(node.path), Source.deleted_at.is_(None))
        )
    ).all()
    for source, notebook in rows:
        for name in {source.vector_collection, (source.metadata_ or {}).get("also_indexed_in")} - {None}:
            await index.set_ancestors(name, source.id, node_ids_from_path(notebook.path))
    return len(rows)


# --- format dispatch ---------------------------------------------------------------------------------


async def _parse_source(
    session: AsyncSession,
    source: Source,
    store: BlobStore,
    gateway: ModelGateway,
    project_id: uuid.UUID,
    job: IngestionJob,
) -> ParsedDocument:
    settings = get_settings()
    if source.kind == SourceKind.web:
        return await _parse_web(session, source, store)
    raw = await store.get(blob_key(source.id, "original"))
    if source.kind == SourceKind.note:
        return parse(raw, "markdown", source.title)
    sniffed = sniff(raw, source.original_path or source.title)
    if sniffed.format in ("zip", "tar"):
        return await _expand_archive(session, source, raw, sniffed.format, store)
    if sniffed.format == "image":
        from opennotebook.ingestion.images import parse_image

        doc, used = await parse_image(raw, source.title, gateway, project_id)
        job.provider_model = ", ".join(used)
        return doc
    if sniffed.format == "pdf":
        first = _pdf_first_pass(raw, source.title)
        if first.scanned_pages:
            return await _pdf_with_ocr(raw, first, source.title, gateway, project_id, job)
        return ensure_content(first)
    if sniffed.format == "code":
        from opennotebook.ingestion.code import parse_code

        return parse_code(decode_text(raw), sniffed.language, source.title, settings.chunk_size_tokens)
    return parse(raw, sniffed.format, source.title)


def _pdf_first_pass(raw: bytes, title: str) -> ParsedDocument:
    try:
        return parse_pdf(raw, title, allow_empty=True)
    except (UnsupportedContent, ParseError):
        raise
    except Exception as exc:  # noqa: BLE001 - library errors on malformed input
        raise ParseError(f"Could not parse PDF: {exc.__class__.__name__}") from exc


async def _pdf_with_ocr(
    raw: bytes,
    first: ParsedDocument,
    title: str,
    gateway: ModelGateway,
    project_id: uuid.UUID,
    job: IngestionJob,
) -> ParsedDocument:
    from opennotebook.ingestion.images import ocr_scanned_pages

    texts, used, warnings = await ocr_scanned_pages(raw, first.scanned_pages, gateway, project_id)
    job.provider_model = ", ".join(used) or None
    doc = parse_pdf(raw, title, ocr_text=texts, allow_empty=True)
    doc.warnings.extend(warnings)
    return ensure_content(doc)


# --- archives ----------------------------------------------------------------------------------------


def _human(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} kB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


async def _delete_children(session: AsyncSession, source: Source) -> None:
    """Re-indexing an archive (or a crawl root) replaces its children."""
    for child in await descendants(session, source.id):
        child.deleted_at = datetime.now(UTC)
        child.note_id = None
    await session.commit()
    for child in await descendants(session, source.id, include_deleted=True):
        if child.deleted_at is not None and child.vector_collection:
            queue.enqueue_purge(child.id)


async def descendants(
    session: AsyncSession, source_id: uuid.UUID, include_deleted: bool = False
) -> list[Source]:
    out: list[Source] = []
    frontier = [source_id]
    while frontier:
        q = select(Source).where(Source.parent_source_id.in_(frontier))
        if not include_deleted:
            q = q.where(Source.deleted_at.is_(None))
        children = list((await session.scalars(q)).all())
        out.extend(children)
        frontier = [c.id for c in children]
    return out


async def _expand_archive(
    session: AsyncSession, source: Source, raw: bytes, fmt: str, store: BlobStore
) -> ParsedDocument:
    settings = get_settings()
    depth = int((source.metadata_ or {}).get("archive_depth", 0))
    await _delete_children(session, source)
    limits = Limits(
        max_total_bytes=settings.archive_max_uncompressed_mb * 1024 * 1024,
        max_files=settings.archive_max_files,
        max_ratio=settings.archive_max_ratio,
        max_file_bytes=settings.upload_max_mb * 1024 * 1024,
    )
    existing = set(
        (
            await session.scalars(
                select(Source.content_sha256).where(
                    Source.notebook_id == source.notebook_id,
                    Source.deleted_at.is_(None),
                    Source.kind != SourceKind.note,
                )
            )
        ).all()
    )
    prefix = source.original_path or source.title
    created: list[Source] = []
    stored_keys: list[str] = []
    files: list[tuple[str, str, int]] = []  # path, label, size
    skipped: list[dict] = []
    total = 0
    try:
        for item in iter_members(raw, fmt, limits):
            if not isinstance(item, Member):
                skipped.append({"path": item.path, "reason": item.reason})
                continue
            total += len(item.data)
            try:
                sniffed = sniff(item.data, item.path)
            except UnsupportedContent as exc:
                skipped.append({"path": item.path, "reason": str(exc)[:200]})
                continue
            if sniffed.kind == "image" and not settings.archive_index_images:
                skipped.append({"path": item.path, "reason": "image (ARCHIVE_INDEX_IMAGES is off)"})
                continue
            if sniffed.kind == "archive" and depth + 1 >= settings.archive_max_depth:
                skipped.append({"path": item.path, "reason": "nested archive deeper than ARCHIVE_MAX_DEPTH"})
                continue
            digest = hashlib.sha256(item.data).digest()
            if digest in existing:
                skipped.append({"path": item.path, "reason": "duplicate of another source in the notebook"})
                continue
            existing.add(digest)
            child = Source(
                id=uuid.uuid4(),
                notebook_id=source.notebook_id,
                parent_source_id=source.id,
                kind=SourceKind(sniffed.kind),
                title=item.path[-500:],
                original_path=f"{prefix}!/{item.path}",
                mime_type=sniffed.mime_type,
                language=sniffed.language,
                content_sha256=digest,
                size_bytes=len(item.data),
                status=SourceStatus.queued,
                created_by=source.created_by,
                active=source.active,
                warnings=[],
                metadata_={"format": sniffed.format, "archive_depth": depth + 1},
            )
            key = blob_key(child.id, "original")
            await store.put(key, item.data, sniffed.mime_type)
            stored_keys.append(key)
            created.append(child)
            files.append((item.path, sniffed.language or sniffed.format, len(item.data)))
    except ArchiveRejected:
        for key in stored_keys:
            await store.delete(key)
        raise

    for child in created:
        session.add(child)
        session.add(
            SourceBlob(
                source_id=child.id,
                role="original",
                object_key=blob_key(child.id, "original"),
                size_bytes=child.size_bytes,
                content_type=child.mime_type or "application/octet-stream",
            )
        )
    source.metadata_ = {
        **(source.metadata_ or {}),
        "archive": {
            "format": fmt,
            "files": len(created),
            "skipped_count": len(skipped),
            "skipped": skipped[:500],
            "uncompressed_bytes": total,
            "depth": depth,
        },
    }
    await session.commit()
    for child in created:
        queue.enqueue_ingestion(child.id, "archive")

    # The archive itself is indexed as its manifest, so "which files are in X" can be answered.
    b = DocumentBuilder(source.title)
    b.heading(f"Contents of {source.title}", 1)
    b.block(
        f"{len(created)} files indexed, {len(skipped)} skipped, "
        f"{_human(total)} uncompressed ({fmt.upper()}).",
        "paragraph",
    )
    by_dir: dict[str, list[str]] = {}
    for path, label, size in files:
        directory = path.rsplit("/", 1)[0] if "/" in path else "."
        by_dir.setdefault(directory, []).append(f"{path} ({label}, {_human(size)})")
    for directory, lines in sorted(by_dir.items()):
        b.heading(f"Directory {directory}", 2)
        for i in range(0, len(lines), 40):
            b.block("\n".join(lines[i : i + 40]), "list")
    if skipped:
        b.heading("Skipped files", 2)
        lines = [f"{s['path']}: {s['reason']}" for s in skipped[:500]]
        for i in range(0, len(lines), 40):
            b.block("\n".join(lines[i : i + 40]), "list")
    return b.build()


# --- web pages ---------------------------------------------------------------------------------------


def web_digest(url: str) -> bytes:
    """Web sources are deduplicated by URL within a notebook."""
    return hashlib.sha256(f"url:{url}".encode()).digest()


async def _parse_web(session: AsyncSession, source: Source, store: BlobStore) -> ParsedDocument:
    if not source.uri:
        raise ParseError("Web source without URL")
    fetched = await fetch(source.uri)
    content_type = fetched.content_type or "text/html"
    key = blob_key(source.id, "original")
    await store.put(key, fetched.data, content_type)
    await session.merge(
        SourceBlob(
            source_id=source.id,
            role="original",
            object_key=key,
            size_bytes=len(fetched.data),
            content_type=content_type,
        )
    )
    meta = dict(source.metadata_ or {})
    meta.update(
        {
            "final_url": fetched.url,
            "content_type": content_type,
            "fetched_at": datetime.now(UTC).isoformat(),
            "content_sha256": hashlib.sha256(fetched.data).hexdigest(),
        }
    )
    if content_type == "application/pdf" or fetched.data.startswith(b"%PDF-"):
        source.mime_type = "application/pdf"
        doc = parse_pdf(fetched.data, source.title)
    else:
        text = decode_text(fetched.data) if _is_utf8(fetched.data) else fetched.data.decode("latin-1")
        if content_type in ("text/html", "application/xhtml+xml") or text.lstrip()[:15].lower().startswith(
            ("<!doctype", "<html")
        ):
            source.mime_type = "text/html"
            doc = parse_html(text, source.title)
            await _crawl(session, source, text, fetched.url, meta)
        elif content_type == "text/markdown":
            source.mime_type = "text/markdown"
            doc = parse_markdown(text, source.title)
        else:
            source.mime_type = "text/plain"
            doc = parse_text(text, source.title)
    if source.title == source.uri and doc.title and doc.title != source.title:
        source.title = doc.title[:500]
    source.size_bytes = len(fetched.data)
    source.metadata_ = meta
    return doc


def _is_utf8(data: bytes) -> bool:
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


async def _crawl(session: AsyncSession, source: Source, html: str, base_url: str, meta: dict) -> None:
    """Bounded crawl: same host, depth and page budget stored on the root page, robots.txt respected."""
    crawl = meta.get("crawl") or {}
    depth_left = int(crawl.get("depth_left", 0))
    if depth_left <= 0:
        return
    root_id = crawl.get("root", str(source.id))
    max_pages = int(crawl.get("max_pages", get_settings().web_crawl_max_pages))
    already = await session.scalar(
        select(func.count(Source.id)).where(
            Source.notebook_id == source.notebook_id,
            Source.metadata_["crawl"]["root"].astext == root_id,
            Source.id != uuid.UUID(root_id),
        )
    )
    budget = max_pages - int(already or 0)
    created: list[Source] = []
    for url in same_host_links(html, base_url):
        if budget <= 0:
            break
        digest = web_digest(url)
        exists = await session.scalar(
            select(Source.id).where(
                Source.notebook_id == source.notebook_id,
                Source.content_sha256 == digest,
                Source.deleted_at.is_(None),
            )
        )
        if exists or not await robots_allows(url):
            continue
        child = Source(
            id=uuid.uuid4(),
            notebook_id=source.notebook_id,
            parent_source_id=source.id,
            kind=SourceKind.web,
            title=url[:500],
            original_path=url,
            uri=url,
            mime_type="text/html",
            content_sha256=digest,
            size_bytes=0,
            status=SourceStatus.queued,
            created_by=source.created_by,
            active=source.active,
            warnings=[],
            metadata_={"crawl": {"root": root_id, "depth_left": depth_left - 1, "max_pages": max_pages}},
        )
        session.add(child)
        created.append(child)
        budget -= 1
    meta["crawl"] = {**crawl, "root": root_id, "links_followed": len(created)}
    await session.commit()  # children must exist before their jobs run
    for child in created:
        queue.enqueue_ingestion(child.id, "crawl")
