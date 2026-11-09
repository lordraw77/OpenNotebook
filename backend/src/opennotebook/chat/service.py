"""Answer one chat question as a stream of server-sent events, persisting both turns.

Events (each `event: <name>` + JSON `data`):
  message   the stored user message
  status    {"stage": "retrieving" | "generating"}
  sources   the numbered passages given to the model (S1..Sn) with their anchors
  provider  the chat model actually used and the failed attempts before it (fallback)
  token     {"text": "..."} answer text as it is generated
  done      the stored assistant message, with validated citations and checks
  error     {"message": "..."} (the assistant message is stored with status "error")
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.acl import get_search_scope
from opennotebook.chat.citations import NOT_FOUND, normalize, strip_markers
from opennotebook.chat.prompt import ContextPassage, build_messages
from opennotebook.chat.retrieval import retrieval_query, retrieve
from opennotebook.config import get_settings
from opennotebook.db import get_sessionmaker
from opennotebook.ingestion.pipeline import node_ids_from_path
from opennotebook.ingestion.search import SearchHit
from opennotebook.ingestion.vectors import get_vector_index
from opennotebook.models import Conversation, Message, User
from opennotebook.providers.gateway import GatewayError, ModelGateway

log = logging.getLogger(__name__)

TITLE_MAX = 80


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, ensure_ascii=False)}\n\n"


def location_of(hit_or_ctx: dict) -> str:
    ps, pe = hit_or_ctx.get("page_start"), hit_or_ctx.get("page_end")
    if ps:
        return f"p. {ps}" if not pe or pe == ps else f"pp. {ps}-{pe}"
    ls, le = hit_or_ctx.get("line_start"), hit_or_ctx.get("line_end")
    if ls:
        return f"lines {ls}-{le}" if le and le != ls else f"line {ls}"
    return ""


def context_entry(n: int, hit: SearchHit) -> dict:
    c = hit.chunk
    return {
        "n": n,
        "chunk_id": str(c.id),
        "source_id": str(hit.source.id),
        "source_title": hit.source.title,
        "source_kind": hit.source.kind.value,
        "mime_type": hit.source.view_mime_type,
        "notebook_id": str(hit.notebook.id),
        "notebook_name": hit.notebook.name,
        "heading_path": list(c.heading_path or []),
        "page_start": c.page_start,
        "page_end": c.page_end,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "char_start": c.char_start,
        "char_end": c.char_end,
        "bboxes": c.bboxes or [],
        "score": hit.score,
        "text": c.text,
    }


def message_out(m: Message) -> dict:
    return {
        "id": str(m.id),
        "conversation_id": str(m.conversation_id),
        "role": m.role,
        "content": m.content,
        "status": m.status,
        "context": m.context or [],
        "citations": m.citations or [],
        "checks": m.checks or {},
        "model_label": m.model_label,
        "attempts": m.attempts or [],
        "usage": m.usage,
        "latency_ms": m.latency_ms,
        "error": m.error,
        "created_at": m.created_at.isoformat() if m.created_at else None,
    }


async def _history(session: AsyncSession, conversation_id: uuid.UUID, before: uuid.UUID) -> list[Message]:
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.conversation_id == conversation_id, Message.id != before)
            .order_by(Message.created_at.desc())
            .limit(get_settings().chat_history_messages)
        )
    ).all()
    return list(reversed(rows))


async def answer_stream(
    conversation_id: uuid.UUID,
    user_id: uuid.UUID,
    question: str,
    model_id: uuid.UUID | None,
    mode: str = "chat",
) -> AsyncIterator[str]:
    """The caller has already checked that the user owns the conversation and can read its scope."""
    settings = get_settings()
    async with get_sessionmaker()() as session:
        user = await session.get(User, user_id)
        conversation = await session.get(Conversation, conversation_id)
        if user is None or conversation is None:  # deleted between the request check and the stream
            yield sse("error", {"message": "Conversation not found"})
            return
        scope = await get_search_scope(session, user, conversation.scope_node_id)

        question_msg = Message(conversation_id=conversation.id, role="user", content=question)
        session.add(question_msg)
        if conversation.title == "New chat":
            conversation.title = question.strip().splitlines()[0][:TITLE_MAX] or "New chat"
        conversation.updated_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(question_msg)
        yield sse("message", message_out(question_msg))

        answer = Message(conversation_id=conversation.id, role="assistant", content="", status="complete")
        text_parts: list[str] = []
        started = time.perf_counter()
        from opennotebook.metrics import CHAT_ANSWERS, CHAT_FIRST_TOKEN

        first_token_seen = False
        try:
            yield sse("status", {"stage": "retrieving"})
            previous = await _history(session, conversation.id, question_msg.id)
            history = [
                {"role": m.role, "content": strip_markers(m.content)}
                for m in previous
                if m.status == "complete" and m.content
            ]
            query = retrieval_query(question, [m.content for m in previous if m.role == "user"])
            project_id = uuid.UUID(node_ids_from_path(scope.path)[0])
            research_plan: list[str] | None = None
            if mode == "research":
                from opennotebook.chat.research import gather, plan

                yield sse("status", {"stage": "planning"})
                subs, planner = await plan(ModelGateway(session), query, project_id, model_id)
                research_plan = [query, *subs]
                yield sse("plan", {"sub_questions": research_plan, "model": planner})
                for i, sub in enumerate(research_plan):
                    yield sse(
                        "status",
                        {"stage": "researching", "step": i + 1, "of": len(research_plan), "question": sub},
                    )
                retrieved = await gather(session, get_vector_index(), user, scope, research_plan)
            else:
                retrieved = await retrieve(session, get_vector_index(), user, scope, query)
            context = [
                {**context_entry(i + 1, h), "via": "graph" if h.chunk.id in retrieved.via_graph else "search"}
                for i, h in enumerate(retrieved.hits)
            ]
            answer.context = context
            answer.checks = {
                "embedding_model": retrieved.embedding_model,
                "rerank_model": retrieved.rerank_model,
                "warnings": retrieved.warnings,
                "mode": mode,
                **({"plan": research_plan} if research_plan else {}),
            }
            yield sse(
                "sources",
                {
                    "context": context,
                    "embedding_model": retrieved.embedding_model,
                    "rerank_model": retrieved.rerank_model,
                    "warnings": retrieved.warnings,
                },
            )

            if not context:
                # Nothing to ground an answer on: abstain without calling a model.
                text_parts.append(NOT_FOUND)
                yield sse("token", {"text": NOT_FOUND})
            else:
                yield sse("status", {"stage": "generating"})
                passages = [
                    ContextPassage(
                        n=c["n"],
                        title=c["source_title"],
                        location=location_of(c),
                        heading=" > ".join(c["heading_path"]),
                        text=c["text"],
                    )
                    for c in context
                ]
                if mode == "research":
                    from opennotebook.chat.research import REPORT_INSTRUCTIONS

                    messages = build_messages(history, passages, question, REPORT_INSTRUCTIONS)
                    max_tokens = settings.research_max_tokens
                else:
                    messages = build_messages(history, passages, question)
                    max_tokens = settings.chat_max_tokens
                async for ev in ModelGateway(session).stream_chat(
                    messages,
                    project_id=project_id,
                    selected_model_id=model_id,
                    first_token_timeout_s=settings.chat_first_token_timeout_s,
                    max_tokens=max_tokens,
                ):
                    if ev.kind == "provider" and ev.used is not None:
                        answer.provider_model_id = ev.used.model.id
                        answer.model_label = ev.used.label
                        answer.attempts = ev.attempts
                        yield sse("provider", {"model": ev.used.label, "attempts": ev.attempts})
                    elif ev.kind == "token":
                        if not first_token_seen:
                            first_token_seen = True
                            CHAT_FIRST_TOKEN.labels(mode).observe(time.perf_counter() - started)
                        text_parts.append(ev.text)
                        yield sse("token", {"text": ev.text})
                    elif ev.kind == "usage":
                        answer.usage = ev.usage
                        answer.latency_ms = ev.latency_ms
        except GatewayError as exc:
            answer.status = "error"
            answer.error = exc.describe()
            answer.attempts = exc.attempts or answer.attempts
            yield sse("error", {"message": answer.error})
        except Exception:  # noqa: BLE001 - report instead of dropping the stream
            log.exception("chat answer failed")
            answer.status = "error"
            answer.error = "Internal error while answering"
            yield sse("error", {"message": answer.error})
        except BaseException:
            answer.status = "stopped"  # client disconnected (stop button) or server shutdown
            raise
        finally:
            check = normalize("".join(text_parts), len(answer.context or []))
            answer.content = check.content.strip()
            answer.citations = [c for c in (answer.context or []) if c["n"] in check.cited]
            answer.checks = {
                **(answer.checks or {}),
                "abstained": check.abstained,
                "uncited_sentences": check.uncited_sentences,
                "invalid_citations": check.invalid,
            }
            if answer.latency_ms is None:
                answer.latency_ms = int((time.perf_counter() - started) * 1000)
            CHAT_ANSWERS.labels(mode, answer.status if not check.abstained else "abstained").inc()
            # Persist even when the client went away: shield the write from cancellation.
            with anyio.CancelScope(shield=True):
                session.add(answer)
                conversation.updated_at = datetime.now(UTC)
                await session.commit()
                await session.refresh(answer)
        yield sse("done", message_out(answer))
