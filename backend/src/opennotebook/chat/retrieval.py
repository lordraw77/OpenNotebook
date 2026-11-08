"""Retrieval for a chat question: hybrid search → optional rerank → per-source diversification."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.ingestion.pipeline import node_ids_from_path
from opennotebook.ingestion.search import SearchHit, search_scope
from opennotebook.ingestion.vectors import VectorIndex
from opennotebook.models import Node, User
from opennotebook.providers.gateway import GatewayError, ModelGateway

log = logging.getLogger(__name__)


@dataclass
class Retrieved:
    hits: list[SearchHit]
    embedding_model: str
    rerank_model: str | None = None
    warnings: list[str] = field(default_factory=list)


def retrieval_query(question: str, previous_questions: list[str]) -> str:
    """Short follow-ups ("and the second one?") are searched together with the previous question."""
    if previous_questions and len(question.split()) < 8:
        return f"{previous_questions[-1]}\n{question}"
    return question


def diversify(hits: list[SearchHit], limit: int, max_per_source: int) -> list[SearchHit]:
    picked: list[SearchHit] = []
    per_source: dict[uuid.UUID, int] = {}
    for h in hits:
        if per_source.get(h.source.id, 0) >= max_per_source:
            continue
        picked.append(h)
        per_source[h.source.id] = per_source.get(h.source.id, 0) + 1
        if len(picked) >= limit:
            break
    return picked


async def retrieve(
    session: AsyncSession, index: VectorIndex, user: User, scope: Node, query: str
) -> Retrieved:
    settings = get_settings()
    hits, embedding_model = await search_scope(
        session, index, user, scope, query, limit=settings.chat_candidates
    )
    result = Retrieved(hits=hits, embedding_model=embedding_model)
    if len(hits) > 1:
        project_id = uuid.UUID(node_ids_from_path(scope.path)[0])
        try:
            ranked = await ModelGateway(session).rerank(
                query,
                [h.chunk.text for h in hits],
                project_id,
                timeout_s=settings.rerank_timeout_s,
            )
        except GatewayError as exc:
            log.warning("rerank failed, keeping fusion order: %s", exc.describe())
            result.warnings.append(f"Rerank skipped: {exc.describe()}")
            ranked = None
        if ranked is not None:
            order = [i for i, _ in ranked.value if 0 <= i < len(hits)]
            seen = set(order)
            # documents the reranker did not return keep their fusion order at the end
            order += [i for i in range(len(hits)) if i not in seen]
            hits = [hits[i] for i in order]
            result.rerank_model = ranked.used.label
    result.hits = diversify(hits, settings.chat_context_chunks, settings.chat_max_per_source)
    return result
