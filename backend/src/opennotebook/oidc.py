"""OpenID Connect (Authorization Code + PKCE) for single sign-on (ADR-009).

The browser is redirected to the identity provider; the callback exchanges the code server side, verifies the
ID token (signature from the provider's JWKS, issuer, audience, expiry, nonce) and maps it to a local account.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import time
from typing import Any

import httpx
import jwt

from opennotebook.config import get_settings

ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512"]
_cache: dict[str, tuple[float, dict]] = {}
CACHE_S = 600


class OidcError(Exception):
    """Sign-in cannot complete; the message is shown to the user."""


async def _get_json(url: str) -> dict:
    async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def _post_form(url: str, data: dict, auth: tuple[str, str] | None) -> dict:
    async with httpx.AsyncClient(timeout=15, trust_env=False) as client:
        response = await client.post(url, data=data, auth=auth, headers={"Accept": "application/json"})
        if response.status_code >= 400:
            raise OidcError(f"The identity provider refused the sign-in (HTTP {response.status_code})")
        return response.json()


async def _cached(url: str, refresh: bool = False) -> dict:
    now = time.monotonic()
    if not refresh and url in _cache and _cache[url][0] > now:
        return _cache[url][1]
    try:
        data = await _get_json(url)
    except (httpx.HTTPError, ValueError) as exc:
        raise OidcError("The identity provider is not reachable") from exc
    _cache[url] = (now + CACHE_S, data)
    return data


async def discovery() -> dict:
    issuer = get_settings().oidc_issuer_url.rstrip("/")
    return await _cached(f"{issuer}/.well-known/openid-configuration")


def redirect_uri() -> str:
    return get_settings().app_public_url.rstrip("/") + "/api/auth/oidc/callback"


def new_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def sign_state(payload: dict) -> str:
    """Short-lived signed cookie carrying state, nonce and the PKCE verifier between login and callback."""
    settings = get_settings()
    return jwt.encode(
        {**payload, "exp": int(time.time()) + 600, "aud": "oidc-state"}, settings.app_secret_key, "HS256"
    )


def read_state(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().app_secret_key, algorithms=["HS256"], audience="oidc-state")
    except jwt.InvalidTokenError as exc:
        raise OidcError("The sign-in attempt expired, try again") from exc


async def authorization_url(state: str, nonce: str, challenge: str) -> str:
    settings = get_settings()
    endpoint = (await discovery())["authorization_endpoint"]
    params = {
        "response_type": "code",
        "client_id": settings.oidc_client_id,
        "redirect_uri": redirect_uri(),
        "scope": settings.oidc_scopes,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return str(httpx.URL(endpoint, params=params))


async def exchange_code(code: str, verifier: str) -> dict:
    settings = get_settings()
    token_endpoint = (await discovery())["token_endpoint"]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(),
        "client_id": settings.oidc_client_id,
        "code_verifier": verifier,
    }
    auth = (settings.oidc_client_id, settings.oidc_client_secret) if settings.oidc_client_secret else None
    return await _post_form(token_endpoint, data, auth)


async def verify_id_token(id_token: str, nonce: str) -> dict[str, Any]:
    settings = get_settings()
    meta = await discovery()
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.InvalidTokenError as exc:
        raise OidcError("Invalid ID token") from exc
    if header.get("alg") not in ALGORITHMS:
        raise OidcError("Unsupported ID token algorithm")
    key = None
    for refresh in (False, True):  # unknown kid: the provider may have rotated its keys
        jwks = await _cached(meta["jwks_uri"], refresh=refresh)
        match = [
            k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid") or header.get("kid") is None
        ]
        if match:
            key = jwt.PyJWK(match[0]).key
            break
    if key is None:
        raise OidcError("The ID token signing key is unknown")
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[header["alg"]],
            audience=settings.oidc_client_id,
            issuer=meta["issuer"],
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            leeway=60,
        )
    except jwt.InvalidTokenError as exc:
        raise OidcError(f"Invalid ID token ({exc.__class__.__name__})") from exc
    if claims.get("nonce") != nonce:
        raise OidcError("Invalid ID token (nonce)")
    return claims


def claim_groups(claims: dict) -> list[str]:
    raw = claims.get(get_settings().oidc_groups_claim) or []
    if isinstance(raw, str):
        raw = [raw]
    return sorted({str(g).strip().strip("/").split("/")[-1] for g in raw if str(g).strip("/ ")})
