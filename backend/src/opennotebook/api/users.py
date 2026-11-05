"""User administration (administrators only)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select

from opennotebook.api.auth import UserOut
from opennotebook.deps import AdminUser, CurrentUser, SessionDep, audit
from opennotebook.models import User
from opennotebook.security import hash_password

router = APIRouter(prefix="/api/users", tags=["users"])


class UserCreate(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12, max_length=256)
    is_admin: bool = False


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=256)
    is_admin: bool | None = None
    is_active: bool | None = None


class UserRef(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


@router.get("", response_model=list[UserOut])
async def list_users(_: AdminUser, session: SessionDep) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.email))).all())


@router.get("/directory", response_model=list[UserRef])
async def directory(_: CurrentUser, session: SessionDep, q: str = "") -> list[User]:
    """Minimal user lookup used when sharing a node (owners need it, not only admins)."""
    stmt = select(User).where(User.is_active.is_(True)).order_by(User.email).limit(20)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.email).like(like) | func.lower(User.display_name).like(like))
    return list((await session.scalars(stmt)).all())


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, admin: AdminUser, session: SessionDep) -> User:
    if await session.scalar(select(User.id).where(func.lower(User.email) == body.email.lower())):
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
    user = User(
        email=body.email.lower(),
        display_name=body.display_name,
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
    )
    session.add(user)
    await session.flush()
    audit(session, admin, "user.create", "user", user.id, email=user.email, is_admin=user.is_admin)
    await session.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, body: UserUpdate, admin: AdminUser, session: SessionDep) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if user.id == admin.id and (body.is_admin is False or body.is_active is False):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You cannot remove your own admin role or disable yourself"
        )
    changes = body.model_dump(exclude_unset=True, exclude={"password"})
    for key, value in changes.items():
        setattr(user, key, value)
    if body.password:
        user.password_hash = hash_password(body.password)
        changes["password"] = "changed"  # noqa: S105 - audit marker, not a secret
    audit(session, admin, "user.update", "user", user.id, **changes)
    await session.commit()
    return user
