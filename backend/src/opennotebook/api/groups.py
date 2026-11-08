"""Groups: administrators manage them; any user can look them up to share a node with a group.

A grant to a group applies to all its members (acl.granted_paths). Groups may also be synchronized from the
identity provider's groups claim at OIDC sign-in (`source = "oidc"`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from opennotebook.deps import AdminUser, CurrentUser, SessionDep, audit
from opennotebook.models import Group, GroupMember, NodeGrant, User

router = APIRouter(prefix="/api/groups", tags=["groups"])


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    source: str = "local"
    members: int = 0


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class MemberOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


async def _group(session: SessionDep, group_id: uuid.UUID) -> Group:
    group = await session.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


async def _out(session: SessionDep, group: Group) -> GroupOut:
    count = await session.scalar(
        select(func.count()).select_from(GroupMember).where(GroupMember.group_id == group.id)
    )
    return GroupOut(
        id=group.id, name=group.name, description=group.description, source=group.source, members=count or 0
    )


@router.get("", response_model=list[GroupOut])
async def list_groups(_: AdminUser, session: SessionDep) -> list[GroupOut]:
    groups = (await session.scalars(select(Group).order_by(Group.name))).all()
    return [await _out(session, g) for g in groups]


@router.get("/directory", response_model=list[GroupOut])
async def directory(
    _: CurrentUser, session: SessionDep, q: str = Query(default="", max_length=200)
) -> list[GroupOut]:
    """Group lookup for the share dialog (names only; members are not disclosed)."""
    stmt = select(Group).order_by(Group.name).limit(20)
    if q:
        stmt = stmt.where(func.lower(Group.name).contains(q.lower(), autoescape=True))
    return [
        GroupOut(id=g.id, name=g.name, description=g.description, source=g.source)
        for g in (await session.scalars(stmt)).all()
    ]


@router.post("", response_model=GroupOut, status_code=201)
async def create_group(body: GroupIn, admin: AdminUser, session: SessionDep) -> GroupOut:
    if await session.scalar(select(Group.id).where(func.lower(Group.name) == body.name.strip().lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "A group with this name exists")
    group = Group(name=body.name.strip(), description=body.description, source="local")
    session.add(group)
    await session.flush()
    audit(session, admin, "group.create", "group", group.id, name=group.name)
    await session.commit()
    return await _out(session, group)


@router.patch("/{group_id}", response_model=GroupOut)
async def update_group(
    group_id: uuid.UUID, body: GroupUpdate, admin: AdminUser, session: SessionDep
) -> GroupOut:
    group = await _group(session, group_id)
    if body.name is not None:
        clash = await session.scalar(
            select(Group.id).where(func.lower(Group.name) == body.name.strip().lower(), Group.id != group.id)
        )
        if clash:
            raise HTTPException(status.HTTP_409_CONFLICT, "A group with this name exists")
        group.name = body.name.strip()
    if body.description is not None:
        group.description = body.description
    audit(session, admin, "group.update", "group", group.id, **body.model_dump(exclude_unset=True))
    await session.commit()
    return await _out(session, group)


@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> None:
    group = await _group(session, group_id)
    await session.execute(
        delete(NodeGrant).where(NodeGrant.principal_type == "group", NodeGrant.principal_id == group.id)
    )
    audit(session, admin, "group.delete", "group", group.id, name=group.name)
    await session.delete(group)
    await session.commit()


@router.get("/{group_id}/members", response_model=list[MemberOut])
async def members(group_id: uuid.UUID, _: AdminUser, session: SessionDep) -> list[User]:
    await _group(session, group_id)
    stmt = (
        select(User)
        .join(GroupMember, GroupMember.user_id == User.id)
        .where(GroupMember.group_id == group_id)
        .order_by(User.email)
    )
    return list((await session.scalars(stmt)).all())


@router.put("/{group_id}/members/{user_id}", status_code=204)
async def add_member(group_id: uuid.UUID, user_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> None:
    await _group(session, group_id)
    if await session.get(User, user_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if await session.get(GroupMember, (group_id, user_id)) is None:
        session.add(GroupMember(group_id=group_id, user_id=user_id))
        audit(session, admin, "group.member_add", "group", group_id, user_id=str(user_id))
        await session.commit()


@router.delete("/{group_id}/members/{user_id}", status_code=204)
async def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, admin: AdminUser, session: SessionDep
) -> None:
    member = await session.get(GroupMember, (group_id, user_id))
    if member is not None:
        await session.delete(member)
        audit(session, admin, "group.member_remove", "group", group_id, user_id=str(user_id))
        await session.commit()
