"""Hybrid retrieval over a scope (precursor of the grounded chat of M2).

The query is embedded with the embedding model of the scope's project, combined with a BM25 sparse query and
fused (RRF) inside Qdrant. Authorization and the on/off switches are applied as pre-filters (ADR-006).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.acl import readable_subtree_roots
from opennotebook.config import get_settings
from opennotebook.ingestion.pipeline import node_ids_from_path
from opennotebook.ingestion.sparse import query_vector
from opennotebook.ingestion.vectors import VectorIndex, collection_for
from opennotebook.models import Chunk, ModelPhase, Node, Source, User
from opennotebook.providers.gateway import ModelGateway


@dataclass
class SearchHit:
    chunk: Chunk
    source: Source
    notebook: Node
    score: float


async def scope_filters(
    session: AsyncSession, user: User, scope: Node
) -> tuple[list[str] | None, list[str], list[str]]:
    """Returns (readable subtree roots or None for all, excluded node ids, excluded source ids)."""
    roots = await readable_subtree_roots(session, user, scope)
    readable = [node_ids_from_path(p)[-1] for p in roots] if roots is not None else None
    inactive_nodes = (
        await session.scalars(
            select(Node.id).where(
                or_(Node.path.op("<@")(scope.path), Node.path.op("@>")(scope.path)),
                Node.active.is_(False),
                Node.deleted_at.is_(None),
            )
        )
    ).all()
    inactive_sources = (
        await session.scalars(
            select(Source.id)
            .join(Node, Node.id == Source.notebook_id)
            .where(
                Node.path.op("<@")(scope.path),
                or_(Source.active.is_(False), Source.deleted_at.is_not(None)),
            )
        )
    ).all()
    return readable, [str(n) for n in inactive_nodes], [str(s) for s in inactive_sources]


async def search_scope(
    session: AsyncSession, index: VectorIndex, user: User, scope: Node, query: str, limit: int = 10
) -> tuple[list[SearchHit], str]:
    project_id = uuid.UUID(node_ids_from_path(scope.path)[0])
    gateway = ModelGateway(session)
    chain = await gateway.resolve(ModelPhase.embedding, project_id)
    embedded = await gateway.embed(
        [query], project_id, input_type="query", timeout_s=get_settings().search_timeout_s
    )
    readable, excluded_nodes, excluded_sources = await scope_filters(session, user, scope)

    hits = await index.search(
        collection_for(chain[0].model.id),
        dense=embedded.value[0],
        sparse=query_vector(query),
        scope_id=str(scope.id),
        readable_roots=readable,
        excluded_nodes=excluded_nodes,
        excluded_sources=excluded_sources,
        limit=limit,
    )
    if not hits:
        return [], embedded.used.label
    scores = {h.chunk_id: h.score for h in hits}
    rows = (
        await session.execute(
            select(Chunk, Source, Node)
            .join(Source, Source.id == Chunk.source_id)
            .join(Node, Node.id == Source.notebook_id)
            .where(Chunk.id.in_(scores), Source.deleted_at.is_(None))
        )
    ).all()
    out = [SearchHit(chunk=c, source=s, notebook=n, score=scores[c.id]) for c, s, n in rows]
    out.sort(key=lambda h: h.score, reverse=True)
    return out, embedded.used.label
