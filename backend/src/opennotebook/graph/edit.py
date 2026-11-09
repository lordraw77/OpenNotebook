"""Manual edits of the knowledge graph (rename, retype, merge, delete, add and remove relations).

The graph is derived from the sources, and a re-index rebuilds a source's entities, mentions and
relations. Edits are therefore recorded so that extraction honours them:
- a renamed entity keeps its name (`Entity.manual_name`);
- a merged entity keeps receiving mentions on the target (`Entity.merged_into`);
- a deleted entity or relation is not created again (`Entity.hidden`, `RelationBlock`);
- manual relations have no source passage, so a re-index does not touch them.
Edits apply to the whole project; callers check the editor role.
"""

from __future__ import annotations

import re
import uuid

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.graph.store import ENTITY_TYPES, display_name
from opennotebook.models import Entity, EntityMention, Relation, RelationBlock, WikiPage


class EditError(ValueError):
    """The edit is not valid; the message is shown to the user."""


def relation_type(value: str) -> str:
    text = re.sub(r"[^a-z0-9_ ]", "", (value or "").lower()).strip().replace(" ", "_")[:60]
    if not text:
        raise EditError("Relation type is required")
    return text


async def _forget_pages(session: AsyncSession, *entity_ids: uuid.UUID) -> None:
    await session.execute(delete(WikiPage).where(WikiPage.entity_id.in_(entity_ids)))


async def edit_entity(session: AsyncSession, entity: Entity, name: str | None, type_: str | None) -> None:
    if name is not None:
        cleaned = display_name(name)
        if not cleaned:
            raise EditError("Name is required")
        entity.manual_name = cleaned
    if type_ is not None:
        if type_ not in ENTITY_TYPES:
            raise EditError(f"Unknown entity type '{type_}'")
        entity.type = type_
    await _forget_pages(session, entity.id)


async def merge_entities(
    session: AsyncSession, source: Entity, target: Entity, target_name: str | None = None
) -> None:
    """Fold `source` into `target`: mentions and relations move, and later extractions follow the merge.

    `target_name` is the name the target shows now; it is pinned so the merged mentions do not rename it.
    """
    if source.id == target.id:
        raise EditError("Choose a different entity to merge into")
    if source.project_id != target.project_id or target.hidden:
        raise EditError("Entities must belong to the same project")
    # mentions of passages the target already mentions would collide on the primary key
    already = select(EntityMention.chunk_id).where(EntityMention.entity_id == target.id)
    await session.execute(
        delete(EntityMention).where(EntityMention.entity_id == source.id, EntityMention.chunk_id.in_(already))
    )
    await session.execute(
        update(EntityMention).where(EntityMention.entity_id == source.id).values(entity_id=target.id)
    )
    await session.execute(update(Relation).where(Relation.src_id == source.id).values(src_id=target.id))
    await session.execute(update(Relation).where(Relation.dst_id == source.id).values(dst_id=target.id))
    await session.execute(delete(Relation).where(Relation.src_id == Relation.dst_id))
    await session.execute(
        delete(RelationBlock).where(or_(RelationBlock.src_id == source.id, RelationBlock.dst_id == source.id))
    )
    await session.execute(update(Entity).where(Entity.merged_into == source.id).values(merged_into=target.id))
    source.merged_into = target.id
    if target_name and not target.manual_name:
        target.manual_name = target_name
    await _forget_pages(session, source.id, target.id)


async def delete_entity(session: AsyncSession, entity: Entity) -> None:
    """Remove an entity and keep extraction from recreating it (also for entities merged into it)."""
    await session.execute(delete(EntityMention).where(EntityMention.entity_id == entity.id))
    await session.execute(
        delete(Relation).where(or_(Relation.src_id == entity.id, Relation.dst_id == entity.id))
    )
    await session.execute(
        update(Entity).where(Entity.merged_into == entity.id).values(hidden=True, merged_into=None)
    )
    entity.hidden = True
    entity.merged_into = None
    await _forget_pages(session, entity.id)


async def add_relation(
    session: AsyncSession, src: Entity, dst: Entity, type_: str, description: str | None
) -> Relation:
    if src.id == dst.id:
        raise EditError("A relation needs two different entities")
    if src.project_id != dst.project_id or src.hidden or dst.hidden:
        raise EditError("Entities must belong to the same project")
    rel_type = relation_type(type_)
    await session.execute(
        delete(RelationBlock).where(
            RelationBlock.project_id == src.project_id,
            RelationBlock.src_id == src.id,
            RelationBlock.dst_id == dst.id,
            RelationBlock.type == rel_type,
        )
    )
    exists = await session.scalar(
        select(func.count())
        .select_from(Relation)
        .where(
            Relation.src_id == src.id, Relation.dst_id == dst.id, Relation.type == rel_type, Relation.manual
        )
    )
    if exists:
        raise EditError("This relation already exists")
    relation = Relation(
        project_id=src.project_id,
        src_id=src.id,
        dst_id=dst.id,
        type=rel_type,
        description=(description or "").strip()[:1000] or None,
        manual=True,
    )
    session.add(relation)
    await session.flush()
    await _forget_pages(session, src.id, dst.id)
    return relation


async def delete_relation(session: AsyncSession, relation: Relation) -> None:
    """Delete a manual relation, or an extracted one together with a tombstone against re-extraction."""
    if not relation.manual:
        await session.execute(
            insert(RelationBlock)
            .values(
                id=uuid.uuid4(),
                project_id=relation.project_id,
                src_id=relation.src_id,
                dst_id=relation.dst_id,
                type=relation.type,
            )
            .on_conflict_do_nothing(constraint="uq_relation_blocks")
        )
        await session.execute(
            delete(Relation).where(
                Relation.project_id == relation.project_id,
                Relation.src_id == relation.src_id,
                Relation.dst_id == relation.dst_id,
                Relation.type == relation.type,
                Relation.manual.is_(False),
            )
        )
    else:
        await session.delete(relation)
    await _forget_pages(session, relation.src_id, relation.dst_id)
