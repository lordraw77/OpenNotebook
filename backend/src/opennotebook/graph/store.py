"""Idempotent writes of entities, mentions and relations (safe with concurrent workers)."""

from __future__ import annotations

import re
import unicodedata
import uuid

from sqlalchemy import delete, exists, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.models import Entity, EntityMention, Relation, WikiPage

ENTITY_TYPES = (
    "person",
    "organization",
    "product",
    "component",
    "technology",
    "concept",
    "location",
    "event",
    "document",
    "standard",
    "file",
    "function",
    "class",
    "struct",
    "interface",
    "module",
)
_ARTICLES = re.compile(r"^(the|a|an|il|lo|la|i|gli|le|l'|un|una|uno)\s+", re.IGNORECASE)


def canonical(name: str) -> str:
    """Key used to merge mentions of the same entity: case, accents-compatible forms, spacing, articles."""
    text = unicodedata.normalize("NFKC", name).casefold().strip()
    text = text.strip(" \t\"'`“”‘’.,;:()[]{}")
    text = _ARTICLES.sub("", text)
    return re.sub(r"\s+", " ", text)[:300]


def display_name(name: str) -> str:
    """Surface form without a leading article ("the WPA3" -> "WPA3"), whitespace collapsed."""
    name = " ".join(name.split())
    stripped = _ARTICLES.sub("", name)
    return (stripped or name)[:300]


def entity_type(value: str | None) -> str:
    value = (value or "").strip().lower().replace(" ", "_")
    return value if value in ENTITY_TYPES else "concept"


class GraphWriter:
    def __init__(self, session: AsyncSession, project_id: uuid.UUID) -> None:
        self.session = session
        self.project_id = project_id
        self._ids: dict[str, uuid.UUID] = {}

    async def entity(self, name: str, type_: str, key: str | None = None) -> uuid.UUID | None:
        name = display_name(name)
        key = key or canonical(name)
        if not key or len(key) < 2:
            return None
        if key in self._ids:
            return self._ids[key]
        await self.session.execute(
            insert(Entity)
            .values(
                id=uuid.uuid4(), project_id=self.project_id, canonical=key, name=name, type=entity_type(type_)
            )
            .on_conflict_do_nothing(constraint="uq_entities_project_canonical")
        )
        entity_id = await self.session.scalar(
            select(Entity.id).where(Entity.project_id == self.project_id, Entity.canonical == key)
        )
        self._ids[key] = entity_id  # type: ignore[assignment]
        return entity_id

    async def mention(
        self,
        entity_id: uuid.UUID,
        chunk_id: uuid.UUID,
        source_id: uuid.UUID,
        name: str,
        description: str | None,
    ) -> None:
        await self.session.execute(
            insert(EntityMention)
            .values(
                entity_id=entity_id,
                chunk_id=chunk_id,
                source_id=source_id,
                name=display_name(name),
                description=(description or "").strip()[:1000] or None,
            )
            .on_conflict_do_nothing()
        )

    async def relation(
        self,
        src: uuid.UUID,
        dst: uuid.UUID,
        type_: str,
        description: str | None,
        chunk_id: uuid.UUID,
        source_id: uuid.UUID,
    ) -> None:
        if src == dst:
            return
        rel_type = re.sub(r"[^a-z0-9_ ]", "", (type_ or "related_to").lower()).strip().replace(" ", "_")[:60]
        self.session.add(
            Relation(
                project_id=self.project_id,
                src_id=src,
                dst_id=dst,
                type=rel_type or "related_to",
                description=(description or "").strip()[:1000] or None,
                chunk_id=chunk_id,
                source_id=source_id,
            )
        )


async def clear_source(session: AsyncSession, source_id: uuid.UUID) -> None:
    """Remove the graph data of one source (before re-extraction or on deletion)."""
    touched = select(EntityMention.entity_id).where(EntityMention.source_id == source_id)
    await session.execute(delete(WikiPage).where(WikiPage.entity_id.in_(touched)))
    await session.execute(delete(Relation).where(Relation.source_id == source_id))
    await session.execute(delete(EntityMention).where(EntityMention.source_id == source_id))


async def drop_orphans(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Entities with neither mentions nor relations (their sources were deleted or re-indexed).

    An entity created only as the target of an import keeps its relation until its own file is indexed;
    queries never show entities without a visible mention.
    """
    await session.execute(
        delete(Entity).where(
            Entity.project_id == project_id,
            ~exists().where(EntityMention.entity_id == Entity.id),
            ~exists().where(Relation.src_id == Entity.id),
            ~exists().where(Relation.dst_id == Entity.id),
        )
    )
