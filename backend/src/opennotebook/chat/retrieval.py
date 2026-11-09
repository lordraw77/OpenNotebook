"""Retrieval for a chat question: hybrid search → optional rerank → per-source diversification."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.ingestion.pipeline import node_ids_from_path
from opennotebook.ingestion.search import SearchHit, search_scope
from opennotebook.ingestion.vectors import VectorIndex
from opennotebook.models import ModelPhase, Node, User
from opennotebook.providers.gateway import GatewayError, ModelGateway

log = logging.getLogger(__name__)


@dataclass
class Retrieved:
    hits: list[SearchHit]
    embedding_model: str
    rerank_model: str | None = None
    warnings: list[str] = field(default_factory=list)
    # chunks added by graph expansion (neighbours of the entities in the retrieved passages)
    via_graph: set[uuid.UUID] = field(default_factory=set)


def retrieval_query(question: str, previous_questions: list[str]) -> str:
    """Fallback without a model rewrite: short follow-ups are searched with the previous question."""
    if previous_questions and len(question.split()) < 8:
        return f"{previous_questions[-1]}\n{question}"
    return question


REWRITE_PROMPT = """Rewrite the last question of this conversation as one standalone search query that can be
understood without the conversation. Resolve pronouns and references ("it", "the second one", "and for the
other case?"), keep names, codes and numbers exactly, and keep the language of the question. If the
question is already standalone, repeat it unchanged. Reply with the query only: no quotes, no explanation,
no answer.

Conversation:
{history}

Last question: {question}"""


def clean_rewrite(reply: str, question: str) -> str | None:
    """The rewritten query, or None when the reply is unusable (empty, an essay, or a refusal to rewrite)."""
    text = " ".join((reply or "").strip().strip("\"'`").split())
    if text.lower().startswith(("query:", "standalone query:")):
        text = text.split(":", 1)[1].strip()
    if not text or len(text) > max(300, 4 * len(question)):
        return None
    return text


async def rewrite_question(
    gateway: ModelGateway,
    question: str,
    turns: list[tuple[str, str]],
    project_id: uuid.UUID,
    model_id: uuid.UUID | None,
) -> tuple[str | None, str | None]:
    """A model turns a follow-up ("and the second one?") into a standalone query using the recent turns.

    Returns (query, model label); (None, None) when there is nothing to resolve or the call fails, in which
    case the caller falls back to `retrieval_query`.
    """
    if not turns:
        return None, None
    history = "\n".join(f"{role}: {' '.join(text.split())[:400]}" for role, text in turns[-4:])
    try:
        result = await asyncio.wait_for(
            gateway.complete(
                ModelPhase.chat,
                [{"role": "user", "content": REWRITE_PROMPT.format(history=history, question=question)}],
                project_id,
                selected_model_id=model_id,
                max_tokens=200,
            ),
            get_settings().chat_rewrite_timeout_s,
        )
    except Exception as exc:  # noqa: BLE001 - a failed rewrite must never fail the answer
        log.warning("follow-up rewrite failed, using the previous question instead: %s", exc)
        return None, None
    try:
        rewritten = clean_rewrite(result.value.choices[0].message.content or "", question)
    except (AttributeError, IndexError, TypeError):
        return None, None
    return (rewritten, result.used.label) if rewritten else (None, None)


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
    from opennotebook.metrics import RETRIEVAL_DURATION, timed

    with timed(RETRIEVAL_DURATION):
        return await _retrieve(session, index, user, scope, query)


async def _retrieve(
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
    if settings.chat_graph_expansion_chunks > 0 and result.hits:
        from opennotebook.graph.query import expansion_hits

        extra = await expansion_hits(
            session, user, scope, [h.chunk.id for h in result.hits], settings.chat_graph_expansion_chunks
        )
        result.hits.extend(extra)
        result.via_graph = {h.chunk.id for h in extra}
    return result
