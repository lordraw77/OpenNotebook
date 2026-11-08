"""Hierarchy: projects, workspaces and notebooks with free nesting, plus per-node grants.

Nesting rules:
  - a project is always a root node;
  - a workspace can be placed under a project or another workspace;
  - a notebook can be placed under a project, a workspace or another notebook.
Maximum depth is NODE_MAX_DEPTH. Moves stay inside the same project (the project defines the embedding model).
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import String, and_, cast, delete, func, select, text, update
from sqlalchemy.exc import IntegrityError

from opennotebook.acl import get_node_for, visible_nodes
from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.ingestion import queue
from opennotebook.models import GrantRole, Group, Node, NodeGrant, NodeKind, Source, User

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

ALLOWED_PARENTS: dict[NodeKind, set[NodeKind]] = {
    NodeKind.project: set(),
    NodeKind.workspace: {NodeKind.project, NodeKind.workspace},
    NodeKind.notebook: {NodeKind.project, NodeKind.workspace, NodeKind.notebook},
}


def slugify(name: str) -> str:
    value = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return value[:200] or "node"


def label(node_id: uuid.UUID) -> str:
    return "n" + node_id.hex  # ltree label: letters/digits/underscore only


class NodeOut(BaseModel):
    id: uuid.UUID
    kind: NodeKind
    parent_id: uuid.UUID | None
    name: str
    slug: str
    depth: int
    active: bool
    role: GrantRole | None = Field(description="Effective role; null = visible only as an ancestor")
    project_id: uuid.UUID


class NodeCreate(BaseModel):
    kind: NodeKind
    name: str = Field(min_length=1, max_length=200)
    parent_id: uuid.UUID | None = None


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    active: bool | None = None
    parent_id: uuid.UUID | None = None


class GrantIn(BaseModel):
    principal_type: Literal["user", "group"]
    principal_id: uuid.UUID
    role: GrantRole


class GrantOut(GrantIn):
    principal_name: str | None = None


def project_id_of(node: Node) -> uuid.UUID:
    return uuid.UUID(hex=node.path.split(".")[0][1:])


def to_out(node: Node, role: GrantRole | None) -> NodeOut:
    return NodeOut(
        id=node.id,
        kind=node.kind,
        parent_id=node.parent_id,
        name=node.name,
        slug=node.slug,
        depth=node.depth,
        active=node.active,
        role=role,
        project_id=project_id_of(node),
    )


def _check_parent(kind: NodeKind, parent: Node | None) -> None:
    allowed = ALLOWED_PARENTS[kind]
    if parent is None and allowed:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"A {kind.value} needs a parent")
    if parent is not None and parent.kind not in allowed:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"A {kind.value} cannot be placed under a {parent.kind.value}",
        )


@router.get("", response_model=list[NodeOut])
async def list_nodes(user: CurrentUser, session: SessionDep) -> list[NodeOut]:
    return [to_out(n, r) for n, r in await visible_nodes(session, user)]


@router.get("/{node_id}", response_model=NodeOut)
async def get_node(node_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> NodeOut:
    node, role = await get_node_for(session, user, node_id)
    return to_out(node, role)


@router.post("", response_model=NodeOut, status_code=201)
async def create_node(body: NodeCreate, user: CurrentUser, session: SessionDep) -> NodeOut:
    parent = None
    if body.parent_id is not None:
        parent, _ = await get_node_for(session, user, body.parent_id, GrantRole.editor)
    _check_parent(body.kind, parent)
    depth = (parent.depth + 1) if parent else 0
    if depth >= get_settings().node_max_depth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Maximum nesting depth reached")

    node_id = uuid.uuid4()
    node = Node(
        id=node_id,
        kind=body.kind,
        parent_id=parent.id if parent else None,
        name=body.name.strip(),
        slug=slugify(body.name),
        path=f"{parent.path}.{label(node_id)}" if parent else label(node_id),
        depth=depth,
        created_by=user.id,
    )
    session.add(node)
    if parent is None:
        session.add(
            NodeGrant(node_id=node_id, principal_type="user", principal_id=user.id, role=GrantRole.owner)
        )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A sibling with the same name already exists") from exc
    audit(session, user, "node.create", "node", node.id, kind=node.kind.value, name=node.name)
    await session.commit()
    _, role = await get_node_for(session, user, node.id)
    return to_out(node, role)


@router.patch("/{node_id}", response_model=NodeOut)
async def update_node(
    node_id: uuid.UUID, body: NodeUpdate, user: CurrentUser, session: SessionDep
) -> NodeOut:
    node, role = await get_node_for(session, user, node_id, GrantRole.editor)
    changes = body.model_dump(exclude_unset=True)

    moved = False
    if "parent_id" in changes and changes["parent_id"] != node.parent_id:
        await _move(session, user, node, body.parent_id)
        moved = True
    if body.name is not None and body.name.strip() != node.name:
        node.name = body.name.strip()
        node.slug = slugify(body.name)
    if body.active is not None and body.active != node.active:
        # The switch applies to the whole subtree (SCP-03).
        await session.execute(
            update(Node)
            .where(Node.path.op("<@")(node.path), Node.deleted_at.is_(None))
            .values(active=body.active)
        )
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A sibling with the same name already exists") from exc
    audit(session, user, "node.update", "node", node.id, **{k: str(v) for k, v in changes.items()})
    await session.commit()
    if moved:
        queue.enqueue_refresh_ancestors(node.id)
    await session.refresh(node)
    return to_out(node, role)


async def _move(session: SessionDep, user: User, node: Node, new_parent_id: uuid.UUID | None) -> None:
    if node.kind == NodeKind.project or new_parent_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Projects cannot be moved; others need a parent"
        )
    new_parent, _ = await get_node_for(session, user, new_parent_id, GrantRole.editor)
    _check_parent(node.kind, new_parent)
    if new_parent.path == node.path or new_parent.path.startswith(node.path + "."):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Cannot move a node inside itself")
    if project_id_of(new_parent) != project_id_of(node):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Nodes can only be moved within their project"
        )
    subtree_height = await session.scalar(select(func.max(Node.depth)).where(Node.path.op("<@")(node.path)))
    new_depth = new_parent.depth + 1
    if new_depth + (subtree_height - node.depth) >= get_settings().node_max_depth:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Move exceeds the maximum nesting depth")

    old_path, new_path = node.path, f"{new_parent.path}.{label(node.id)}"
    delta = new_depth - node.depth
    await session.execute(
        text(
            "UPDATE nodes SET path = CASE WHEN path = CAST(:old AS ltree) THEN CAST(:new AS ltree) "
            "ELSE CAST(:new AS ltree) || subpath(path, nlevel(CAST(:old AS ltree))) END, "
            "depth = depth + :delta WHERE path <@ CAST(:old AS ltree)"
        ),
        {"new": new_path, "old": old_path, "delta": delta},
    )
    node.parent_id = new_parent.id
    await session.flush()
    await session.refresh(node)


@router.delete("/{node_id}", status_code=204)
async def delete_node(node_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> None:
    node, _ = await get_node_for(session, user, node_id, GrantRole.owner)
    now = datetime.now(UTC)
    # Soft delete of the subtree; slugs are freed by suffixing so a sibling can reuse the name.
    await session.execute(
        update(Node)
        .where(Node.path.op("<@")(node.path), Node.deleted_at.is_(None))
        .values(deleted_at=now, slug=func.concat(Node.slug, "~", func.substr(cast(Node.id, String), 1, 8)))
    )
    source_ids = (
        await session.scalars(
            select(Source.id)
            .join(Node, Node.id == Source.notebook_id)
            .where(Node.path.op("<@")(node.path), Source.deleted_at.is_(None))
        )
    ).all()
    await session.execute(update(Source).where(Source.id.in_(source_ids)).values(deleted_at=now))
    audit(session, user, "node.delete", "node", node.id, name=node.name, sources=len(source_ids))
    await session.commit()
    for sid in source_ids:
        queue.enqueue_purge(sid)


# --- grants -----------------------------------------------------------------------------------


@router.get("/{node_id}/grants", response_model=list[GrantOut])
async def list_grants(node_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> list[GrantOut]:
    node, _ = await get_node_for(session, user, node_id, GrantRole.owner)
    grants = (await session.scalars(select(NodeGrant).where(NodeGrant.node_id == node.id))).all()
    out = []
    for g in grants:
        if g.principal_type == "user":
            u = await session.get(User, g.principal_id)
            name = u.email if u else None
        else:
            grp = await session.get(Group, g.principal_id)
            name = grp.name if grp else None
        out.append(
            GrantOut(
                principal_type=g.principal_type, principal_id=g.principal_id, role=g.role, principal_name=name
            )
        )  # type: ignore[arg-type]
    return out


@router.put("/{node_id}/grants", response_model=GrantOut)
async def put_grant(node_id: uuid.UUID, body: GrantIn, user: CurrentUser, session: SessionDep) -> GrantOut:
    node, _ = await get_node_for(session, user, node_id, GrantRole.owner)
    target = User if body.principal_type == "user" else Group
    if await session.get(target, body.principal_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{body.principal_type} not found")
    existing = await session.get(NodeGrant, (node.id, body.principal_type, body.principal_id))
    if existing:
        existing.role = body.role
    else:
        session.add(NodeGrant(node_id=node.id, **body.model_dump()))
    audit(session, user, "grant.put", "node", node.id, **body.model_dump(mode="json"))
    await session.commit()
    return GrantOut(**body.model_dump())


@router.delete("/{node_id}/grants/{principal_type}/{principal_id}", status_code=204)
async def delete_grant(
    node_id: uuid.UUID,
    principal_type: Literal["user", "group"],
    principal_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
) -> None:
    node, _ = await get_node_for(session, user, node_id, GrantRole.owner)
    owners = await session.scalar(
        select(func.count())
        .select_from(NodeGrant)
        .where(and_(NodeGrant.node_id == node.id, NodeGrant.role == GrantRole.owner))
    )
    grant = await session.get(NodeGrant, (node.id, principal_type, principal_id))
    if grant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grant not found")
    if node.kind == NodeKind.project and grant.role == GrantRole.owner and owners == 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "A project must keep at least one owner")
    await session.execute(
        delete(NodeGrant).where(
            NodeGrant.node_id == node.id,
            NodeGrant.principal_type == principal_type,
            NodeGrant.principal_id == principal_id,
        )
    )
    audit(
        session,
        user,
        "grant.delete",
        "node",
        node.id,
        principal_type=principal_type,
        principal_id=str(principal_id),
    )
    await session.commit()
