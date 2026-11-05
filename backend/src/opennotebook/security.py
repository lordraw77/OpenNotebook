"""Password hashing (argon2id), access tokens (JWT) and refresh tokens."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from opennotebook.config import get_settings

_hasher = PasswordHasher()
JWT_ALG = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(user_id: uuid.UUID, is_admin: bool) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "adm": is_admin,
        "iat": now,
        "exp": now + timedelta(seconds=settings.access_token_ttl_s),
        "typ": "access",
    }
    return jwt.encode(payload, settings.app_secret_key, algorithm=JWT_ALG)


def decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, get_settings().app_secret_key, algorithms=[JWT_ALG])
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload


def new_refresh_token() -> tuple[str, bytes]:
    """Returns (opaque token for the cookie, sha256 digest to store)."""
    token = secrets.token_urlsafe(48)
    return token, hash_refresh_token(token)


def hash_refresh_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()
