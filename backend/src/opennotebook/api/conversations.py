"""Conversations of the grounded chat. Each conversation belongs to one user and one scope node."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from opennotebook.acl import get_search_scope, visible_nodes
from opennotebook.chat.service import answer_stream, location_of, message_out
from opennotebook.deps import CurrentUser, SessionDep
from opennotebook.models import Conversation, Message

router = APIRouter(prefix="/api/conversations", tags=["chat"])


class ConversationOut(BaseModel):
    id: uuid.UUID
    scope_node_id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationOut):
    messages: list[dict]


class ConversationIn(BaseModel):
    scope_id: uuid.UUID
    title: str | None = Field(default=None, min_length=1, max_length=300)


class ConversationUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=300)


class QuestionIn(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    model_id: uuid.UUID | None = None
    # "research": plan sub-questions, retrieve for each, write a structured cited report
    mode: Literal["chat", "research"] = "chat"


async def _own(session: SessionDep, user: CurrentUser, conversation_id: uuid.UUID) -> Conversation:
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    # access to the scope may have been revoked since the conversation was created
    await get_search_scope(session, user, conv.scope_node_id)
    return conv


class HistoryItem(ConversationOut):
    scope_name: str
    scope_kind: str
    message_count: int
    # the first question, and for a search the passage of a message that matched
    first_question: str | None = None
    match: str | None = None
    research: bool = False


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _snippet(text: str, needle: str, width: int = 90) -> str:
    flat = " ".join(text.split())
    at = flat.casefold().find(needle.casefold())
    if at < 0:
        return flat[: 2 * width]
    start = max(0, at - width)
    return (
        ("…" if start else "")
        + flat[start : at + len(needle) + width]
        + ("…" if len(flat) > at + width else "")
    )


@router.get("/history", response_model=list[HistoryItem])
async def history(
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    q: str | None = Query(default=None, max_length=200),
    scope_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[HistoryItem]:
    """All of the user's conversations, most recent first, across scopes the user can still read.

    `q` searches the titles and the text of every message; `scope_id` limits to a node and what is below it.
    """
    from opennotebook.models import Node

    readable = {n.id: n for n, role in await visible_nodes(session, user) if role is not None}
    wanted = set(readable)
    if scope_id is not None:
        scope = readable.get(scope_id)
        if scope is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
        wanted = {
            i for i, n in readable.items() if n.path == scope.path or n.path.startswith(scope.path + ".")
        }
    base = select(Conversation).where(Conversation.user_id == user.id, Conversation.scope_node_id.in_(wanted))
    if q and q.strip():
        pattern = f"%{_escape_like(q.strip())}%"
        in_messages = (
            select(Message.conversation_id)
            .where(Message.content.ilike(pattern, escape="\\"))
            .scalar_subquery()
        )
        base = base.where(
            or_(Conversation.title.ilike(pattern, escape="\\"), Conversation.id.in_(in_messages))
        )
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    response.headers["X-Total-Count"] = str(total or 0)
    rows = (
        await session.scalars(base.order_by(Conversation.updated_at.desc()).limit(limit).offset(offset))
    ).all()
    if not rows:
        return []
    ids = [c.id for c in rows]
    counts = dict(
        (
            await session.execute(
                select(Message.conversation_id, func.count())
                .where(Message.conversation_id.in_(ids))
                .group_by(Message.conversation_id)
            )
        ).all()
    )
    firsts: dict[uuid.UUID, str] = {}
    research: set[uuid.UUID] = set()
    for message in (
        await session.scalars(
            select(Message).where(Message.conversation_id.in_(ids)).order_by(Message.created_at)
        )
    ).all():
        if message.role == "user" and message.conversation_id not in firsts:
            firsts[message.conversation_id] = " ".join(message.content.split())[:200]
        if (message.checks or {}).get("mode") == "research":
            research.add(message.conversation_id)
    matches: dict[uuid.UUID, str] = {}
    if q and q.strip():
        needle = q.strip()
        for message in (
            await session.scalars(
                select(Message)
                .where(
                    Message.conversation_id.in_(ids),
                    Message.content.ilike(f"%{_escape_like(needle)}%", escape="\\"),
                )
                .order_by(Message.created_at)
            )
        ).all():
            matches.setdefault(message.conversation_id, _snippet(message.content, needle))
    out: list[HistoryItem] = []
    for conv in rows:
        node: Node = readable[conv.scope_node_id]
        out.append(
            HistoryItem(
                **ConversationOut.model_validate(conv).model_dump(),
                scope_name=node.name,
                scope_kind=node.kind.value,
                message_count=int(counts.get(conv.id, 0)),
                first_question=firsts.get(conv.id),
                match=matches.get(conv.id),
                research=conv.id in research,
            )
        )
    return out


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> PlainTextResponse:
    """The conversation as Markdown: questions, answers and the numbered sources each answer cites."""
    conv = await _own(session, user, conversation_id)
    messages = (
        await session.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )
    ).all()
    lines = [f"# {conv.title}", "", f"_{conv.updated_at:%Y-%m-%d %H:%M} UTC_", ""]
    for m in messages:
        if m.role == "user":
            lines += [f"## {' '.join(m.content.split())[:200]}", ""]
            continue
        lines += [m.content or f"_({m.status})_", ""]
        if m.citations:
            lines.append("Sources:")
            for c in m.citations:
                place = location_of(c)
                where = f", {place}" if place else ""
                lines.append(f"- [S{c['n']}] {c['source_title']}{where}")
            lines.append("")
    name = (
        "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in conv.title)[:60].strip()
        or "conversation"
    )
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.md"'},
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[Conversation]:
    await get_search_scope(session, user, scope_id)
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.scope_node_id == scope_id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
    )
    return list((await session.scalars(stmt)).all())


@router.post("", response_model=ConversationOut, status_code=201)
async def create_conversation(body: ConversationIn, user: CurrentUser, session: SessionDep) -> Conversation:
    scope = await get_search_scope(session, user, body.scope_id)
    conv = Conversation(scope_node_id=scope.id, user_id=user.id, title=body.title or "New chat")
    session.add(conv)
    await session.commit()
    await session.refresh(conv)
    return conv


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep
) -> ConversationDetail:
    conv = await _own(session, user, conversation_id)
    messages = (
        await session.scalars(
            select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at)
        )
    ).all()
    return ConversationDetail(
        **ConversationOut.model_validate(conv).model_dump(), messages=[message_out(m) for m in messages]
    )


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def rename_conversation(
    conversation_id: uuid.UUID, body: ConversationUpdate, user: CurrentUser, session: SessionDep
) -> Conversation:
    conv = await _own(session, user, conversation_id)
    conv.title = body.title
    await session.commit()
    await session.refresh(conv)
    return conv


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(conversation_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    conv = await _own(session, user, conversation_id)
    await session.delete(conv)
    await session.commit()


@router.post("/{conversation_id}/messages")
async def ask(
    conversation_id: uuid.UUID, body: QuestionIn, user: CurrentUser, session: SessionDep
) -> StreamingResponse:
    """Ask a question; the answer streams as server-sent events (see opennotebook.chat.service)."""
    from opennotebook.config import get_settings
    from opennotebook.ratelimit import too_many_attempts

    conv = await _own(session, user, conversation_id)
    settings = get_settings()
    limit = settings.chat_rate_limit_per_minute
    if limit and await too_many_attempts(f"chat:{user.id}", limit, 60):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many questions: wait a minute and retry")
    hourly = settings.research_rate_limit_per_hour
    if body.mode == "research" and hourly and await too_many_attempts(f"research:{user.id}", hourly, 3600):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Deep research limit reached for this hour")
    return StreamingResponse(
        answer_stream(conv.id, user.id, body.content.strip(), body.model_id, body.mode),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
