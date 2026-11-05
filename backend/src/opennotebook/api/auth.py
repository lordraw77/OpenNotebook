"""Local authentication: login, refresh-token rotation, logout, current user."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update

from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.models import RefreshToken, User
from opennotebook.ratelimit import too_many_attempts
from opennotebook.security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "on_refresh"


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    is_admin: bool
    is_active: bool

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int
    user: UserOut


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_s,
        httponly=True,
        secure=settings.app_public_url.startswith("https://"),
        samesite="strict",
        path="/api/auth",
    )


async def _issue(session: SessionDep, response: Response, user: User) -> TokenOut:
    settings = get_settings()
    token, digest = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=digest,
            expires_at=datetime.now(UTC) + timedelta(seconds=settings.refresh_token_ttl_s),
        )
    )
    await session.commit()
    _set_refresh_cookie(response, token)
    return TokenOut(
        access_token=create_access_token(user.id, user.is_admin),
        expires_in=settings.access_token_ttl_s,
        user=UserOut.model_validate(user),
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    client_ip = request.client.host if request.client else "unknown"
    if await too_many_attempts(f"login:{client_ip}:{body.email.lower()}", limit=10, window_s=300):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts, retry later")
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not user.is_active or not verify_password(user.password_hash, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    audit(session, user, "auth.login", "user", user.id)
    return await _issue(session, response, user)


@router.post("/refresh", response_model=TokenOut)
async def refresh(request: Request, response: Response, session: SessionDep) -> TokenOut:
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "No refresh token")
    row = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(token))
    )
    now = datetime.now(UTC)
    if row is None or row.expires_at <= now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if row.revoked_at is not None:
        # Reuse of a rotated token: revoke every session of the user.
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == row.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token reuse detected")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User disabled")
    row.revoked_at = now
    return await _issue(session, response, user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, session: SessionDep) -> None:
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.token_hash == hash_refresh_token(token), RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        await session.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
