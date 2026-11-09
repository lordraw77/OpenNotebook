"""Visibility-filtered reads of the knowledge graph.

Every read goes through `visible_sources`: an entity exists for a user only through mentions in sources they
can see, a relation only when its evidence passage is visible and both ends are visible entities, and the
displayed name is the most frequent visible surface form.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.graph.store import canonical
from opennotebook.ingestion.search import SearchHit
from opennotebook.models import Chunk, Entity, EntityMention, Node, Relation, Source, User
from opennotebook.visibility import visible_sources


@dataclass
class EntityRow:
    id: uuid.UUID
    name: str
    type: str
    mentions: int
    sources: int


async def _names(session: AsyncSession, visible: Select, entity_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not entity_ids:
        return {}
    rows = await session.execute(
        select(EntityMention.entity_id, EntityMention.name, func.count())
        .where(EntityMention.entity_id.in_(entity_ids), EntityMention.source_id.in_(visible))
        .group_by(EntityMention.entity_id, EntityMention.name)
    )
    best: dict[uuid.UUID, tuple[int, str]] = {}
    for entity_id, name, count in rows.all():
        if entity_id not in best or count > best[entity_id][0]:
            best[entity_id] = (count, name)
    return {k: v[1] for k, v in best.items()}


async def list_entities(
    session: AsyncSession,
    user: User,
    scope: Node,
    *,
    query: str | None = None,
    types: list[str] | None = None,
    limit: int = 100,
) -> list[EntityRow]:
    visible = await visible_sources(session, user, scope)
    stmt = (
        select(
            Entity.id,
            Entity.type,
            func.count(EntityMention.chunk_id).label("mentions"),
            func.count(func.distinct(EntityMention.source_id)).label("sources"),
        )
        .join(EntityMention, EntityMention.entity_id == Entity.id)
        .where(EntityMention.source_id.in_(visible))
        .group_by(Entity.id, Entity.type)
        .order_by(func.count(EntityMention.chunk_id).desc(), Entity.canonical)
        .limit(limit)
    )
    if query:
        stmt = stmt.where(Entity.canonical.contains(canonical(query), autoescape=True))
    if types:
        stmt = stmt.where(Entity.type.in_(types))
    rows = (await session.execute(stmt)).all()
    names = await _names(session, visible, [r.id for r in rows])
    return [EntityRow(r.id, names.get(r.id, "?"), r.type, r.mentions, r.sources) for r in rows]


async def graph_view(
    session: AsyncSession, user: User, scope: Node, limit: int = 150
) -> tuple[list[EntityRow], list[dict]]:
    nodes = await list_entities(session, user, scope, limit=limit)
    ids = [n.id for n in nodes]
    if not ids:
        return [], []
    visible = await visible_sources(session, user, scope)
    rows = await session.execute(
        select(Relation.src_id, Relation.dst_id, Relation.type, func.count())
        .where(Relation.src_id.in_(ids), Relation.dst_id.in_(ids), Relation.source_id.in_(visible))
        .group_by(Relation.src_id, Relation.dst_id, Relation.type)
    )
    edges = [{"source": str(s), "target": str(d), "type": t, "weight": n} for s, d, t, n in rows.all()]
    return nodes, edges


async def entity_detail(session: AsyncSession, user: User, scope: Node, entity_id: uuid.UUID) -> dict | None:
    visible = await visible_sources(session, user, scope)
    entity = await session.get(Entity, entity_id)
    if entity is None:
        return None
    mentions = (
        await session.execute(
            select(EntityMention, Chunk, Source, Node)
            .join(Chunk, Chunk.id == EntityMention.chunk_id)
            .join(Source, Source.id == EntityMention.source_id)
            .join(Node, Node.id == Source.notebook_id)
            .where(EntityMention.entity_id == entity_id, EntityMention.source_id.in_(visible))
            .order_by(Source.title, Chunk.ordinal)
        )
    ).all()
    if not mentions:
        return None  # not visible to this user in this scope: same answer as a missing entity
    names = Counter(m.name for m, *_ in mentions)
    main_name = names.most_common(1)[0][0]
    aliases = list(
        {
            n.casefold(): n for n, _ in reversed(names.most_common()) if n.casefold() != main_name.casefold()
        }.values()
    )[:5]
    relations = (
        (
            await session.execute(
                select(Relation).where(
                    or_(Relation.src_id == entity_id, Relation.dst_id == entity_id),
                    Relation.source_id.in_(visible),
                )
            )
        )
        .scalars()
        .all()
    )
    others = list({r.dst_id if r.src_id == entity_id else r.src_id for r in relations})
    other_names = await _names(session, visible, others)
    other_types = (
        dict((await session.execute(select(Entity.id, Entity.type).where(Entity.id.in_(others)))).all())
        if others
        else {}
    )
    related: dict[tuple[str, str, uuid.UUID], dict] = {}
    for r in relations:
        other = r.dst_id if r.src_id == entity_id else r.src_id
        if other not in other_names:  # the other end has no visible mention: hide the relation
            continue
        direction = "out" if r.src_id == entity_id else "in"
        key = (direction, r.type, other)
        item = related.setdefault(
            key,
            {
                "entity_id": str(other),
                "name": other_names[other],
                "type": other_types.get(other, "concept"),
                "relation": r.type,
                "direction": direction,
                "description": r.description,
                "count": 0,
                "chunk_id": str(r.chunk_id),
            },
        )
        item["count"] += 1
    return {
        "id": str(entity.id),
        "name": main_name,
        "aliases": aliases,
        "type": entity.type,
        "descriptions": list(dict.fromkeys(m.description for m, *_ in mentions if m.description))[:10],
        "mentions": [
            {
                "chunk": chunk,
                "source": source,
                "notebook": notebook,
                "description": mention.description,
            }
            for mention, chunk, source, notebook in mentions
        ],
        "related": sorted(related.values(), key=lambda x: (-x["count"], x["name"])),
    }


def score_expansion(
    seed_weight: dict[uuid.UUID, float],
    relations: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]],
    neighbour_chunks: dict[uuid.UUID, list[uuid.UUID]],
) -> dict[uuid.UUID, float]:
    """Scores candidate passages for graph expansion.

    `seed_weight` holds the entities of the retrieved passages, weighted by the rank of the best passage that
    mentions them (1 for the top passage, 1/2, 1/3...). The passage stating a relation scores the sum of the
    weights of its seed ends - a passage linking two relevant entities (the bridge of a multi-hop question)
    beats one hanging off a marginal entity; a passage mentioning a non-seed neighbour scores half the weight
    of the seed it hangs off.
    """
    score: dict[uuid.UUID, float] = defaultdict(float)
    for src, dst, evidence in relations:
        score[evidence] += seed_weight.get(src, 0.0) + seed_weight.get(dst, 0.0)
        for seed, neighbour in ((src, dst), (dst, src)):
            if seed in seed_weight and neighbour not in seed_weight:
                for chunk_id in neighbour_chunks.get(neighbour, []):
                    score[chunk_id] += seed_weight[seed] / 2
    return score


async def expansion_hits(
    session: AsyncSession, user: User, scope: Node, chunk_ids: list[uuid.UUID], limit: int
) -> list[SearchHit]:
    """Passages about the 1-hop neighbours of the entities mentioned in the retrieved passages.

    `chunk_ids` are in retrieval order: entities of higher-ranked passages weigh more (see `score_expansion`).
    The relation evidence and the neighbours' mentions are both restricted to visible sources.
    """
    if not chunk_ids or limit <= 0:
        return []
    visible = await visible_sources(session, user, scope)
    rank = {cid: i for i, cid in enumerate(chunk_ids)}
    seed_weight: dict[uuid.UUID, float] = {}
    for entity_id, chunk_id in (
        await session.execute(
            select(EntityMention.entity_id, EntityMention.chunk_id).where(
                EntityMention.chunk_id.in_(chunk_ids), EntityMention.source_id.in_(visible)
            )
        )
    ).all():
        weight = 1 / (1 + rank[chunk_id])
        seed_weight[entity_id] = max(seed_weight.get(entity_id, 0.0), weight)
    if not seed_weight:
        return []
    seeds = list(seed_weight)
    relations = [
        (src, dst, evidence)
        for src, dst, evidence in (
            await session.execute(
                select(Relation.src_id, Relation.dst_id, Relation.chunk_id).where(
                    or_(Relation.src_id.in_(seeds), Relation.dst_id.in_(seeds)),
                    Relation.source_id.in_(visible),
                )
            )
        ).all()
    ]
    neighbours = {e for src, dst, _ in relations for e in (src, dst) if e not in seed_weight}
    neighbour_chunks: dict[uuid.UUID, list[uuid.UUID]] = {}
    for entity_id in neighbours:
        neighbour_chunks[entity_id] = list(
            (
                await session.scalars(
                    select(EntityMention.chunk_id)
                    .where(EntityMention.entity_id == entity_id, EntityMention.source_id.in_(visible))
                    .limit(3)
                )
            ).all()
        )
    score = score_expansion(seed_weight, relations, neighbour_chunks)
    for cid in chunk_ids:
        score.pop(cid, None)
    best = [cid for cid, _ in sorted(score.items(), key=lambda item: -item[1])[:limit]]
    if not best:
        return []
    rows = (
        await session.execute(
            select(Chunk, Source, Node)
            .join(Source, Source.id == Chunk.source_id)
            .join(Node, Node.id == Source.notebook_id)
            .where(Chunk.id.in_(best), Source.id.in_(visible))
        )
    ).all()
    order = {cid: i for i, cid in enumerate(best)}
    hits = [SearchHit(chunk=c, source=s, notebook=n, score=0.0) for c, s, n in rows]
    return sorted(hits, key=lambda h: order[h.chunk.id])
