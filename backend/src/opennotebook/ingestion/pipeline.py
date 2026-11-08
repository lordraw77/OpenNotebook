"""Ingestion and maintenance operations, independent from Celery so they can be tested directly.

Error handling:
  - UnsupportedContent / ParseError -> source `failed`, not retried;
  - GatewayError (provider down, rate limited, no model configured) -> RetryableError, retried with backoff by
    the worker; the source keeps its current status and the last error;
  - anything else -> source `failed` with the error class name.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.ingestion import PIPELINE_VERSION
from opennotebook.ingestion.chunker import chunk_document, embedding_text
from opennotebook.ingestion.parsers import ParseError, UnsupportedContent, parse, sniff
from opennotebook.ingestion.sparse import document_vector
from opennotebook.ingestion.vectors import PointData, VectorIndex, collection_for
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
        raw = await store.get(blob_key(source.id, "original"))
        fmt = (
            sniff(raw, source.original_path or source.title).format
            if source.kind != SourceKind.note
            else "markdown"
        )
        doc = parse(raw, fmt, source.title)
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
        source.metadata_ = {
            **(source.metadata_ or {}),
            "page_sizes": doc.page_sizes,
            "detected_title": doc.title,
        }

        await _set_status(session, source, SourceStatus.chunking)
        chunks = chunk_document(doc, settings.chunk_size_tokens, settings.chunk_overlap_tokens)
        await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
        rows = [
            Chunk(
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

        gateway = ModelGateway(session)
        chain = await gateway.resolve(ModelPhase.embedding, project_id)
        model = chain[0].model
        collection = collection_for(model.id)
        job.provider_model = chain[0].label
        vectors: list[list[float]] = []
        batch = max(1, settings.embed_batch_size)
        title = source.title
        for i in range(0, len(chunks), batch):
            result = await gateway.embed(
                [embedding_text(title, c) for c in chunks[i : i + batch]], project_id, input_type="passage"
            )
            vectors.extend(result.value)
        if len(vectors) != len(rows):
            raise GatewayError(f"Embedding provider returned {len(vectors)} vectors for {len(rows)} chunks")

        await index.ensure_collection(collection, len(vectors[0]))
        if source.vector_collection and source.vector_collection != collection:
            await index.delete_source(source.vector_collection, source.id)
        await index.delete_source(collection, source.id)
        payload_base = {
            "source_id": str(source.id),
            "notebook_id": str(notebook.id),
            "project_id": str(project_id),
            "ancestors": ancestors,
        }
        await index.upsert(
            collection,
            [
                PointData(
                    chunk_id=row.id,
                    dense=vec,
                    sparse=document_vector(embedding_text(title, c)),
                    payload={**payload_base, "chunk_id": str(row.id), "page": c.page_start},
                )
                for row, c, vec in zip(rows, chunks, vectors, strict=True)
            ],
        )
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
        await session.commit()
        return SourceStatus.ready

    except (UnsupportedContent, ParseError) as exc:
        await _fail(session, source_id, job_id, "parse_error", str(exc))
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
    if source.vector_collection:
        await index.delete_source(source.vector_collection, source.id)
    for blob in (await session.scalars(select(SourceBlob).where(SourceBlob.source_id == source.id))).all():
        await store.delete(blob.object_key)
    await session.execute(delete(SourceBlob).where(SourceBlob.source_id == source.id))
    await session.execute(delete(Chunk).where(Chunk.source_id == source.id))
    source.chunk_count = 0
    source.vector_collection = None
    await session.commit()


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
        if source.vector_collection:
            await index.set_ancestors(source.vector_collection, source.id, node_ids_from_path(notebook.path))
    return len(rows)
