"""Which sources a user may see in a scope - the single rule behind retrieval and the knowledge graph.

A source is visible when it is ready and not deleted, its notebook lies under the scope and inside a subtree
the user can read, and neither the source nor any node on its path is switched off (ADR-006, threat T1).
Graph data (mentions, relations, wiki pages) is always filtered through this, never by a post-filter on
results.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Select, and_, false, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.acl import readable_subtree_roots
from opennotebook.models import Node, Source, SourceStatus, User


async def visible_sources(session: AsyncSession, user: User, scope: Node) -> Select[tuple[uuid.UUID]]:
    """A `SELECT sources.id` usable as a subquery (`Source.id.in_(...)`)."""
    readable = await readable_subtree_roots(session, user, scope)
    inactive_paths = (
        await session.scalars(
            select(Node.path).where(
                or_(Node.path.op("<@")(scope.path), Node.path.op("@>")(scope.path)),
                Node.active.is_(False),
                Node.deleted_at.is_(None),
            )
        )
    ).all()
    conditions = [
        Node.path.op("<@")(scope.path),
        Node.deleted_at.is_(None),
        Source.deleted_at.is_(None),
        Source.active.is_(True),
        Source.status == SourceStatus.ready,
    ]
    if readable is not None:
        conditions.append(or_(*[Node.path.op("<@")(r) for r in readable]) if readable else false())
    conditions += [not_(Node.path.op("<@")(p)) for p in inactive_paths]
    return select(Source.id).join(Node, Node.id == Source.notebook_id).where(and_(*conditions))
