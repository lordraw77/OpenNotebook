"""Authentication: local passwords and/or OpenID Connect single sign-on, refresh-token rotation, logout,
current user."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, update

from opennotebook.config import get_settings
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.models import Group, GroupMember, RefreshToken, User
from opennotebook.ratelimit import too_many_attempts
from opennotebook.security import (
    create_access_token,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "on_refresh"
OIDC_COOKIE = "on_oidc"


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


async def _new_session(session: SessionDep, response: Response, user: User) -> None:
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


class AuthConfigOut(BaseModel):
    password: bool
    oidc: bool
    oidc_label: str


@router.get("/config", response_model=AuthConfigOut)
async def auth_config() -> AuthConfigOut:
    """Sign-in methods offered by the login page (public)."""
    settings = get_settings()
    return AuthConfigOut(
        password=settings.password_login_enabled, oidc=settings.oidc_enabled, oidc_label=settings.oidc_label
    )


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, request: Request, response: Response, session: SessionDep) -> TokenOut:
    if not get_settings().password_login_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Password sign-in is disabled: use single sign-on")
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


# --- OpenID Connect -----------------------------------------------------------------------------------


def _login_error(message: str) -> RedirectResponse:
    response = RedirectResponse(f"/login?error={quote(message)}", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    return response


def _safe_next(target: str | None) -> str:
    """Only same-site paths after sign-in (no open redirect)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


@router.get("/oidc/login")
async def oidc_login(next: str | None = Query(default=None)) -> RedirectResponse:  # noqa: A002
    from opennotebook import oidc

    if not get_settings().oidc_enabled:
        return _login_error("Single sign-on is not configured")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = oidc.new_pkce()
    try:
        url = await oidc.authorization_url(state, nonce, challenge)
    except oidc.OidcError as exc:
        return _login_error(str(exc))
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        OIDC_COOKIE,
        oidc.sign_state({"state": state, "nonce": nonce, "verifier": verifier, "next": _safe_next(next)}),
        max_age=600,
        httponly=True,
        secure=get_settings().app_public_url.startswith("https://"),
        samesite="lax",  # the callback is a top-level navigation coming from the identity provider
        path="/api/auth/oidc",
    )
    return response


@router.get("/oidc/callback")
async def oidc_callback(
    request: Request,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> RedirectResponse:
    from opennotebook import oidc

    settings = get_settings()
    if not settings.oidc_enabled:
        return _login_error("Single sign-on is not configured")
    if error:
        return _login_error(f"Sign-in cancelled or refused: {error_description or error}"[:200])
    cookie = request.cookies.get(OIDC_COOKIE)
    try:
        if not cookie or not code or not state:
            raise oidc.OidcError("The sign-in attempt expired, try again")
        saved = oidc.read_state(cookie)
        if not secrets.compare_digest(saved["state"], state):
            raise oidc.OidcError("The sign-in attempt does not match, try again")
        tokens = await oidc.exchange_code(code, saved["verifier"])
        if not tokens.get("id_token"):
            raise oidc.OidcError("The identity provider returned no ID token")
        claims = await oidc.verify_id_token(tokens["id_token"], saved["nonce"])
        user = await _oidc_user(session, claims)
    except oidc.OidcError as exc:
        return _login_error(str(exc))
    audit(session, user, "auth.login_oidc", "user", user.id, sub=claims["sub"])
    response = RedirectResponse(saved.get("next") or "/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    await _new_session(session, response, user)
    return response


async def _oidc_user(session: SessionDep, claims: dict) -> User:
    """Find the account by subject, then by verified email; create it if allowed; sync admin and groups."""
    from opennotebook import oidc

    settings = get_settings()
    sub = str(claims["sub"])
    email = str(claims.get("email") or "").strip().lower()
    if claims.get("email_verified") is False and not settings.oidc_allow_unverified_email:
        raise oidc.OidcError("Your email address is not verified at the identity provider")
    user = await session.scalar(select(User).where(User.oidc_subject == sub))
    if user is None and email:
        user = await session.scalar(select(User).where(func.lower(User.email) == email))
        if user is not None:
            if user.oidc_subject and user.oidc_subject != sub:
                raise oidc.OidcError("This email is linked to another single sign-on identity")
            user.oidc_subject = sub
    if user is None:
        if not settings.oidc_auto_create_users:
            raise oidc.OidcError("No account for this identity: ask an administrator to create it")
        if not email:
            raise oidc.OidcError("The identity provider did not share an email address")
        name = claims.get("name") or claims.get("preferred_username") or email.split("@")[0]
        user = User(email=email, display_name=str(name)[:200], password_hash=None, oidc_subject=sub)
        session.add(user)
        await session.flush()
    if not user.is_active:
        raise oidc.OidcError("Your account is disabled")

    groups = oidc.claim_groups(claims)
    admin_groups = {g.strip() for g in settings.oidc_admin_groups.split(",") if g.strip()}
    if admin_groups:
        user.is_admin = bool(admin_groups & set(groups))
    if settings.oidc_sync_groups:
        await _sync_groups(session, user, groups)
    await session.flush()
    return user


async def _sync_groups(session: SessionDep, user: User, names: list[str]) -> None:
    """Membership of groups named in the token; SSO-managed groups the token no longer lists are left.
    Local groups with the same name are joined but never left automatically."""
    wanted: set[uuid.UUID] = set()
    for name in names:
        group = await session.scalar(select(Group).where(func.lower(Group.name) == name.lower()))
        if group is None:
            group = Group(name=name[:200], source="oidc")
            session.add(group)
            await session.flush()
        wanted.add(group.id)
        if await session.get(GroupMember, (group.id, user.id)) is None:
            session.add(GroupMember(group_id=group.id, user_id=user.id))
    current = (
        await session.execute(
            select(GroupMember, Group)
            .join(Group, Group.id == GroupMember.group_id)
            .where(GroupMember.user_id == user.id, Group.source == "oidc")
        )
    ).all()
    for member, group in current:
        if group.id not in wanted:
            await session.delete(member)
