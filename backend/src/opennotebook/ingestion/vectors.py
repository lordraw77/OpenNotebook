"""Vector index on Qdrant: one collection per embedding model, dense + BM25 sparse vectors, scoped filtering.

Payload of each point (one per chunk): chunk_id, source_id, notebook_id, project_id, ancestors (ids of every
node from the project down to the notebook). Search filters are applied inside each prefetch (ADR-006),
never after the fusion: scope, readable subtrees, and exclusions for switched-off nodes and sources.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import lru_cache

from qdrant_client import AsyncQdrantClient, models

from opennotebook.config import get_settings

DENSE = "dense"
SPARSE = "bm25"


def collection_for(model_id: uuid.UUID) -> str:
    return f"chunks__{model_id.hex}"


@dataclass
class PointData:
    chunk_id: uuid.UUID
    dense: list[float]
    sparse: tuple[list[int], list[float]]
    payload: dict


@dataclass
class Hit:
    chunk_id: uuid.UUID
    score: float


class VectorIndex:
    def __init__(self, client: AsyncQdrantClient) -> None:
        self.client = client

    async def ensure_collection(self, name: str, dim: int) -> None:
        if await self.client.collection_exists(name):
            info = await self.client.get_collection(name)
            vectors = info.config.params.vectors
            size = vectors[DENSE].size if isinstance(vectors, dict) else None
            if size is not None and size != dim:
                raise ValueError(f"Collection {name} has dimension {size}, model returned {dim}")
            return
        await self.client.create_collection(
            name,
            vectors_config={DENSE: models.VectorParams(size=dim, distance=models.Distance.COSINE)},
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field_name in ("ancestors", "source_id", "project_id"):
            await self.client.create_payload_index(name, field_name, models.PayloadSchemaType.KEYWORD)

    async def upsert(self, name: str, points: list[PointData]) -> None:
        if not points:
            return
        await self.client.upsert(
            name,
            points=[
                models.PointStruct(
                    id=str(p.chunk_id),
                    vector={
                        DENSE: p.dense,
                        SPARSE: models.SparseVector(indices=p.sparse[0], values=p.sparse[1]),
                    },
                    payload=p.payload,
                )
                for p in points
            ],
            wait=True,
        )

    async def delete_source(self, name: str, source_id: uuid.UUID) -> None:
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(
            name,
            points_selector=models.FilterSelector(filter=_match("source_id", str(source_id))),
            wait=True,
        )

    async def delete_project(self, name: str, project_id: uuid.UUID) -> None:
        """Remove every vector of a project from one collection (old index after a switch)."""
        if not await self.client.collection_exists(name):
            return
        await self.client.delete(
            name,
            points_selector=models.FilterSelector(filter=_match("project_id", str(project_id))),
            wait=True,
        )

    async def set_ancestors(self, name: str, source_id: uuid.UUID, ancestors: list[str]) -> None:
        if not await self.client.collection_exists(name):
            return
        await self.client.set_payload(
            name, payload={"ancestors": ancestors}, points=_match("source_id", str(source_id)), wait=True
        )

    async def count(self, name: str) -> int:
        if not await self.client.collection_exists(name):
            return 0
        return (await self.client.count(name, exact=True)).count

    async def count_source(self, name: str, source_id: uuid.UUID) -> int:
        if not await self.client.collection_exists(name):
            return 0
        return (
            await self.client.count(name, count_filter=_match("source_id", str(source_id)), exact=True)
        ).count

    async def collections(self) -> list[str]:
        return [
            c.name for c in (await self.client.get_collections()).collections if c.name.startswith("chunks__")
        ]

    async def source_ids(self, name: str) -> set[str]:
        """Distinct source ids that have points in a collection (payload scroll, no vectors)."""
        ids: set[str] = set()
        offset = None
        while True:
            points, offset = await self.client.scroll(
                name, limit=1000, offset=offset, with_payload=["source_id"], with_vectors=False
            )
            ids.update(str(p.payload.get("source_id")) for p in points if p.payload)
            if offset is None:
                return ids

    async def search(
        self,
        name: str,
        *,
        dense: list[float],
        sparse: tuple[list[int], list[float]],
        scope_id: str,
        readable_roots: list[str] | None,
        excluded_nodes: list[str],
        excluded_sources: list[str],
        limit: int = 10,
        prefetch_limit: int = 50,
    ) -> list[Hit]:
        if not await self.client.collection_exists(name):
            return []
        must: list[models.Condition] = [_cond("ancestors", scope_id)]
        if readable_roots is not None:
            if not readable_roots:
                return []
            must.append(models.FieldCondition(key="ancestors", match=models.MatchAny(any=readable_roots)))
        must_not: list[models.Condition] = []
        if excluded_nodes:
            must_not.append(models.FieldCondition(key="ancestors", match=models.MatchAny(any=excluded_nodes)))
        if excluded_sources:
            must_not.append(
                models.FieldCondition(key="source_id", match=models.MatchAny(any=excluded_sources))
            )
        flt = models.Filter(must=must, must_not=must_not or None)

        prefetch = [models.Prefetch(query=dense, using=DENSE, filter=flt, limit=prefetch_limit)]
        if sparse[0]:
            prefetch.append(
                models.Prefetch(
                    query=models.SparseVector(indices=sparse[0], values=sparse[1]),
                    using=SPARSE,
                    filter=flt,
                    limit=prefetch_limit,
                )
            )
        result = await self.client.query_points(
            name,
            prefetch=prefetch,
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            query_filter=flt,
            limit=limit,
            with_payload=False,
        )
        return [Hit(chunk_id=uuid.UUID(str(p.id)), score=p.score) for p in result.points]

    async def close(self) -> None:
        await self.client.close()


def _cond(key: str, value: str) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=value))


def _match(key: str, value: str) -> models.Filter:
    return models.Filter(must=[_cond(key, value)])


def make_vector_index() -> VectorIndex:
    settings = get_settings()
    if settings.qdrant_location:
        return VectorIndex(AsyncQdrantClient(location=settings.qdrant_location))
    return VectorIndex(
        AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key or None, timeout=30)
    )


@lru_cache
def get_vector_index() -> VectorIndex:
    """Process-wide index client (the in-memory mode keeps its data inside this single client)."""
    return make_vector_index()
