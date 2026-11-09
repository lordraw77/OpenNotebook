"""Conversations of the grounded chat. Each conversation belongs to one user and one scope node."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from opennotebook.acl import get_search_scope
from opennotebook.chat.service import answer_stream, message_out
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
