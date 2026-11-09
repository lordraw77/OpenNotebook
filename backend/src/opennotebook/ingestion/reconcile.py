"""Consistency check between PostgreSQL (source of truth), Qdrant (vectors) and object storage (files).

Findings:
  - ready sources whose vector count differs from their chunk count, or with no vectors at all;
  - ready sources whose original file is missing from storage;
  - sources stuck in a processing state for more than an hour (lost job);
  - vectors of sources that no longer exist (orphans).
`fix=True` re-queues ingestion for the first three and deletes orphan vectors.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.ingestion import queue
from opennotebook.ingestion.pipeline import blob_key
from opennotebook.ingestion.vectors import VectorIndex
from opennotebook.models import Chunk, Source, SourceKind, SourceStatus
from opennotebook.storage import BlobStore

STUCK = (SourceStatus.queued, SourceStatus.parsing, SourceStatus.chunking, SourceStatus.embedding)


async def reconcile(
    session: AsyncSession, index: VectorIndex, store: BlobStore, *, fix: bool = False
) -> dict:
    report: dict = {
        "sources_checked": 0,
        "vector_mismatch": [],
        "missing_file": [],
        "stuck": [],
        "orphan_vectors": {},
        "fixed": {"requeued": 0, "orphan_sources_removed": 0},
    }
    chunk_counts = dict(
        (await session.execute(select(Chunk.source_id, func.count()).group_by(Chunk.source_id))).all()
    )
    sources = list((await session.scalars(select(Source).where(Source.deleted_at.is_(None)))).all())
    requeue: set[uuid.UUID] = set()
    for source in sources:
        report["sources_checked"] += 1
        if source.status == SourceStatus.ready:
            chunks = chunk_counts.get(source.id, 0)
            vectors = (
                await index.count_source(source.vector_collection, source.id)
                if source.vector_collection
                else 0
            )
            if chunks and vectors != chunks:
                report["vector_mismatch"].append(
                    {"source_id": str(source.id), "title": source.title, "chunks": chunks, "vectors": vectors}
                )
                requeue.add(source.id)
            if source.kind != SourceKind.web and not await store.exists(blob_key(source.id, "original")):
                report["missing_file"].append({"source_id": str(source.id), "title": source.title})
        elif source.status in STUCK and source.updated_at < datetime.now(UTC) - timedelta(hours=1):
            report["stuck"].append(
                {"source_id": str(source.id), "title": source.title, "status": source.status.value}
            )
            requeue.add(source.id)

    live = {str(s.id) for s in sources}
    for collection in await index.collections():
        orphans = sorted(await index.source_ids(collection) - live)
        if orphans:
            report["orphan_vectors"][collection] = orphans

    if fix:
        for source in sources:
            if source.id in requeue:
                source.status = SourceStatus.queued
                source.error = None
        await session.commit()
        for source_id in requeue:
            queue.enqueue_ingestion(source_id, "reconcile")
        report["fixed"]["requeued"] = len(requeue)
        for collection, orphans in report["orphan_vectors"].items():
            for source_id in orphans:
                await index.delete_source(collection, uuid.UUID(source_id))
                report["fixed"]["orphan_sources_removed"] += 1
    report["ok"] = not (
        report["vector_mismatch"] or report["missing_file"] or report["stuck"] or report["orphan_vectors"]
    )
    return report
