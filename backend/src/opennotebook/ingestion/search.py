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
from opennotebook.providers.gateway import GatewayError, ModelGateway

RRF_K = 60


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
    from opennotebook.ingestion.index_state import serving_model_id

    project_id = uuid.UUID(node_ids_from_path(scope.path)[0])
    gateway = ModelGateway(session)
    chain = await gateway.resolve(ModelPhase.embedding, project_id)
    configured = chain[0].model.id
    # US-08: while an embedding change is re-indexing, sources already moved are in the configured model's
    # index and the others in the serving one: query both and fuse by rank.
    serving = await serving_model_id(session, project_id) or configured
    model_ids = [serving]
    if serving != configured and await index.count(collection_for(configured)) > 0:
        model_ids.append(configured)  # nothing re-indexed yet: the serving index alone answers
    timeout = get_settings().search_timeout_s
    readable, excluded_nodes, excluded_sources = await scope_filters(session, user, scope)

    ranked: list[list[uuid.UUID]] = []
    scores_by_list: list[dict[uuid.UUID, float]] = []
    labels: list[str] = []
    failure: GatewayError | None = None
    for model_id in model_ids:
        try:
            embedded = await gateway.embed(
                [query], project_id, input_type="query", timeout_s=timeout, model_id=model_id
            )
        except (
            GatewayError
        ) as exc:  # e.g. the serving model was disabled or removed: the other index still answers
            failure = exc
            continue
        labels.append(embedded.used.label)
        found = await index.search(
            collection_for(model_id),
            dense=embedded.value[0],
            sparse=query_vector(query),
            scope_id=str(scope.id),
            readable_roots=readable,
            excluded_nodes=excluded_nodes,
            excluded_sources=excluded_sources,
            limit=limit,
        )
        ranked.append([h.chunk_id for h in found])
        scores_by_list.append({h.chunk_id: h.score for h in found})
    if not labels:
        raise failure  # type: ignore[misc] - set whenever no model answered
    label = " + ".join(labels)
    if len(ranked) == 1:
        scores = scores_by_list[0]
    else:  # reciprocal rank fusion across the two indexes (scores of different models are not comparable)
        scores = {}
        for ids in ranked:
            for position, chunk_id in enumerate(ids):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + position + 1)
        best = sorted(scores, key=lambda c: -scores[c])[:limit]
        scores = {c: scores[c] for c in best}
    if not scores:
        return [], label
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
    return out, label
