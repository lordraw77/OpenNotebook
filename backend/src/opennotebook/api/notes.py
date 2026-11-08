"""Notes of a notebook.

An indexed note is mirrored by a source of kind `note` and searched like any other source.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.acl import get_node_for
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.ingestion import queue
from opennotebook.ingestion.pipeline import blob_key
from opennotebook.models import (
    Conversation,
    GrantRole,
    Message,
    NodeKind,
    Note,
    Source,
    SourceBlob,
    SourceKind,
    SourceStatus,
    User,
)
from opennotebook.storage import get_blob_store

router = APIRouter(prefix="/api", tags=["notes"])


class NoteOut(BaseModel):
    id: uuid.UUID
    notebook_id: uuid.UUID
    title: str
    body_md: str
    origin: str
    citations: list
    indexed: bool
    source_id: uuid.UUID | None = None
    source_status: SourceStatus | None = None
    created_at: datetime
    updated_at: datetime


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body_md: str = Field(default="", max_length=200_000)
    indexed: bool = False
    # Save a chat answer: body and citations are copied from the stored message (not from the client).
    from_message_id: uuid.UUID | None = None


CITATION_KEYS = (
    "n",
    "chunk_id",
    "source_id",
    "source_title",
    "source_kind",
    "mime_type",
    "notebook_id",
    "notebook_name",
    "heading_path",
    "page_start",
    "page_end",
    "line_start",
    "line_end",
    "char_start",
    "char_end",
    "bboxes",
)


async def _chat_answer(session: AsyncSession, user: User, message_id: uuid.UUID) -> Message:
    message = await session.get(Message, message_id)
    conv = await session.get(Conversation, message.conversation_id) if message else None
    if message is None or conv is None or conv.user_id != user.id or message.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return message


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    body_md: str | None = Field(default=None, max_length=200_000)
    indexed: bool | None = None


def note_markdown(note: Note) -> str:
    return f"# {note.title}\n\n{note.body_md}".strip() + "\n"


async def _mirror(session: AsyncSession, note: Note) -> Source | None:
    return await session.scalar(select(Source).where(Source.note_id == note.id, Source.deleted_at.is_(None)))


async def _out(session: AsyncSession, note: Note) -> NoteOut:
    src = await _mirror(session, note)
    return NoteOut(
        id=note.id,
        notebook_id=note.notebook_id,
        title=note.title,
        body_md=note.body_md,
        origin=note.origin,
        citations=note.citations or [],
        indexed=note.indexed,
        source_id=src.id if src else None,
        source_status=src.status if src else None,
        created_at=note.created_at,
        updated_at=note.updated_at,
    )


async def sync_note_source(session: AsyncSession, note: Note, user: User) -> None:
    """Create, refresh or remove the source mirroring the note, according to `note.indexed`."""
    source = await _mirror(session, note)
    if not note.indexed:
        if source is not None:
            source.deleted_at = datetime.now(UTC)
            source.note_id = None  # free the unique link so indexing can be enabled again
            await session.commit()
            queue.enqueue_purge(source.id)
        return
    content = note_markdown(note).encode()
    digest = hashlib.sha256(content).digest()
    if source is not None and source.content_sha256 == digest and source.title == note.title:
        return
    if source is None:
        source = Source(
            id=uuid.uuid4(),
            notebook_id=note.notebook_id,
            note_id=note.id,
            kind=SourceKind.note,
            title=note.title,
            original_path=f"{note.title}.md",
            mime_type="text/markdown",
            content_sha256=digest,
            size_bytes=len(content),
            created_by=user.id,
            warnings=[],
            metadata_={"format": "markdown"},
        )
        session.add(source)
    source.title = note.title
    source.content_sha256 = digest
    source.size_bytes = len(content)
    source.status = SourceStatus.queued
    source.error = None
    await get_blob_store().put(blob_key(source.id, "original"), content, "text/markdown")
    await session.merge(
        SourceBlob(
            source_id=source.id,
            role="original",
            object_key=blob_key(source.id, "original"),
            size_bytes=len(content),
            content_type="text/markdown",
        )
    )
    await session.commit()
    queue.enqueue_ingestion(source.id, "note")


async def _note_for(session: AsyncSession, user: User, note_id: uuid.UUID, role: GrantRole) -> Note:
    note = await session.get(Note, note_id)
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    await get_node_for(session, user, note.notebook_id, role)
    return note


@router.get("/nodes/{notebook_id}/notes", response_model=list[NoteOut])
async def list_notes(notebook_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[NoteOut]:
    notebook, _ = await get_node_for(session, user, notebook_id)
    notes = (
        await session.scalars(
            select(Note).where(Note.notebook_id == notebook.id).order_by(Note.updated_at.desc())
        )
    ).all()
    return [await _out(session, n) for n in notes]


@router.post("/nodes/{notebook_id}/notes", response_model=NoteOut, status_code=201)
async def create_note(
    notebook_id: uuid.UUID, body: NoteIn, user: CurrentUser, session: SessionDep
) -> NoteOut:
    notebook, _ = await get_node_for(session, user, notebook_id, GrantRole.editor)
    if notebook.kind != NodeKind.notebook:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Notes belong to a notebook")
    origin, citations, body_md = "manual", [], body.body_md
    if body.from_message_id is not None:
        answer = await _chat_answer(session, user, body.from_message_id)
        origin = "chat"
        body_md = body.body_md or answer.content
        citations = [
            {k: c.get(k) for k in CITATION_KEYS} | {"excerpt": (c.get("text") or "")[:400]}
            for c in answer.citations or []
        ]
    note = Note(
        notebook_id=notebook.id,
        title=body.title.strip(),
        body_md=body_md,
        indexed=body.indexed,
        created_by=user.id,
        origin=origin,
        citations=citations,
    )
    session.add(note)
    await session.flush()
    audit(session, user, "note.create", "note", note.id, indexed=note.indexed)
    await session.commit()
    await sync_note_source(session, note, user)
    await session.refresh(note)
    return await _out(session, note)


@router.patch("/notes/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: uuid.UUID, body: NoteUpdate, user: CurrentUser, session: SessionDep
) -> NoteOut:
    note = await _note_for(session, user, note_id, GrantRole.editor)
    if body.title is not None:
        note.title = body.title.strip()
    if body.body_md is not None:
        note.body_md = body.body_md
    if body.indexed is not None:
        note.indexed = body.indexed
    note.updated_at = datetime.now(UTC)
    await session.commit()
    await sync_note_source(session, note, user)
    await session.refresh(note)
    return await _out(session, note)


@router.delete("/notes/{note_id}", status_code=204)
async def delete_note(note_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    note = await _note_for(session, user, note_id, GrantRole.editor)
    note.indexed = False
    await sync_note_source(session, note, user)
    await session.delete(note)
    audit(session, user, "note.delete", "note", note_id)
    await session.commit()
