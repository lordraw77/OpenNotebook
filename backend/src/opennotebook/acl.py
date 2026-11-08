"""Hierarchical permissions.

A grant on a node applies to the node and every descendant (downward inheritance). The effective role of a
user on a node is the highest role among the grants, for the user or one of their groups, on that node or on
any ancestor. Administrators are owners everywhere. Nodes the user cannot read are reported as "not found"
so that their existence does not leak.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.models import ROLE_RANK, GrantRole, GroupMember, Node, NodeGrant, User


@dataclass(frozen=True)
class GrantedPath:
    path: str
    role: GrantRole


def is_ancestor_or_self(ancestor: str, path: str) -> bool:
    return path == ancestor or path.startswith(ancestor + ".")


async def granted_paths(session: AsyncSession, user: User) -> list[GrantedPath]:
    group_ids = select(GroupMember.group_id).where(GroupMember.user_id == user.id)
    rows = await session.execute(
        select(Node.path, NodeGrant.role)
        .join(Node, Node.id == NodeGrant.node_id)
        .where(
            Node.deleted_at.is_(None),
            or_(
                and_(NodeGrant.principal_type == "user", NodeGrant.principal_id == user.id),
                and_(NodeGrant.principal_type == "group", NodeGrant.principal_id.in_(group_ids)),
            ),
        )
    )
    return [GrantedPath(path=p, role=r) for p, r in rows.all()]


def role_for_path(grants: list[GrantedPath], path: str) -> GrantRole | None:
    best: GrantRole | None = None
    for g in grants:
        if is_ancestor_or_self(g.path, path) and (best is None or ROLE_RANK[g.role] > ROLE_RANK[best]):
            best = g.role
    return best


async def effective_role(session: AsyncSession, user: User, node: Node) -> GrantRole | None:
    if user.is_admin:
        return GrantRole.owner
    return role_for_path(await granted_paths(session, user), node.path)


async def get_node_for(
    session: AsyncSession, user: User, node_id: uuid.UUID, min_role: GrantRole = GrantRole.viewer
) -> tuple[Node, GrantRole]:
    node = await session.get(Node, node_id)
    if node is None or node.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    role = await effective_role(session, user, node)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if ROLE_RANK[role] < ROLE_RANK[min_role]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires role '{min_role.value}' on this node")
    return node, role


async def visible_nodes(session: AsyncSession, user: User) -> list[tuple[Node, GrantRole | None]]:
    """Nodes the user can read, plus their ancestors as navigation-only entries (role None)."""
    base = select(Node).where(Node.deleted_at.is_(None)).order_by(Node.depth, Node.name)
    if user.is_admin:
        return [(n, GrantRole.owner) for n in (await session.scalars(base)).all()]

    grants = await granted_paths(session, user)
    if not grants:
        return []
    paths = [g.path for g in grants]
    # path <@ ANY(granted) -> readable subtree; path @> ANY(granted) -> ancestors for navigation
    conds = [Node.path.op("<@")(p) for p in paths] + [Node.path.op("@>")(p) for p in paths]
    nodes = (await session.scalars(base.where(or_(*conds)))).all()
    return [(n, role_for_path(grants, n.path)) for n in nodes]


async def readable_subtree_roots(session: AsyncSession, user: User, scope: Node) -> list[str] | None:
    """Paths under `scope` the user may read. None means the whole scope is readable.

    This is the pre-filter used by retrieval (ADR-006): results must come only from these subtrees.
    """
    if user.is_admin:
        return None
    grants = await granted_paths(session, user)
    if role_for_path(grants, scope.path) is not None:
        return None
    return sorted({g.path for g in grants if is_ancestor_or_self(scope.path, g.path)})


async def get_search_scope(session: AsyncSession, user: User, node_id: uuid.UUID) -> Node:
    """A scope can be searched when the user reads it, or reads at least one subtree below it.

    In the second case results are limited to those subtrees by `readable_subtree_roots` (pre-filter).
    """
    node = await session.get(Node, node_id)
    if node is None or node.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    if await effective_role(session, user, node) is not None:
        return node
    if await readable_subtree_roots(session, user, node):
        return node
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
