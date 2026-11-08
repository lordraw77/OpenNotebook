"""OpenID Connect sign-in against a scripted identity provider (discovery, JWKS, token endpoint)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

from opennotebook import oidc
from opennotebook.config import get_settings
from opennotebook.models import Group, GroupMember, User
from tests.conftest import make_user

ISSUER = "https://idp.example.com/realms/acme"
CLIENT = "opennotebook"


class FakeIdP:
    def __init__(self) -> None:
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key()))
        self.jwks = {"keys": [{**jwk, "kid": "k1", "alg": "RS256", "use": "sig"}]}
        self.claims: dict = {}
        self.challenge: str | None = None
        self.overrides: dict = {}

    async def get_json(self, url: str) -> dict:
        if url.endswith("/.well-known/openid-configuration"):
            return {
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/protocol/openid-connect/auth",
                "token_endpoint": f"{ISSUER}/protocol/openid-connect/token",
                "jwks_uri": f"{ISSUER}/protocol/openid-connect/certs",
            }
        assert url.endswith("/certs")
        return self.jwks

    async def post_form(self, url: str, data: dict, auth) -> dict:  # type: ignore[no-untyped-def]
        assert data["grant_type"] == "authorization_code" and data["code"] == "good-code"
        assert auth == (CLIENT, "s3cret")
        digest = hashlib.sha256(data["code_verifier"].encode()).digest()
        assert base64.urlsafe_b64encode(digest).rstrip(b"=").decode() == self.challenge  # PKCE
        now = int(time.time())
        claims = {"iss": ISSUER, "aud": CLIENT, "iat": now, "exp": now + 300, **self.claims, **self.overrides}
        return {"id_token": jwt.encode(claims, self.key, "RS256", headers={"kid": "k1"}), "access_token": "x"}


@pytest.fixture
def idp(monkeypatch):
    fake = FakeIdP()
    oidc._cache.clear()
    monkeypatch.setattr(oidc, "_get_json", fake.get_json)
    monkeypatch.setattr(oidc, "_post_form", fake.post_form)
    settings = get_settings()
    for key, value in {
        "auth_mode": "both",
        "oidc_issuer_url": ISSUER,
        "oidc_client_id": CLIENT,
        "oidc_client_secret": "s3cret",
        "oidc_admin_groups": "nb-admins",
        "app_public_url": "http://notebook.test",
    }.items():
        monkeypatch.setattr(settings, key, value)
    yield fake
    oidc._cache.clear()


async def sign_in(client, idp: FakeIdP, claims: dict, next_path: str | None = "/wiki", tamper=None):  # type: ignore[no-untyped-def]
    r = await client.get("/api/auth/oidc/login", params={"next": next_path} if next_path else None)
    assert r.status_code == 302, r.text
    url = urlsplit(r.headers["location"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == f"{ISSUER}/protocol/openid-connect/auth"
    assert query["redirect_uri"] == "http://notebook.test/api/auth/oidc/callback"
    assert query["code_challenge_method"] == "S256" and query["scope"] == "openid email profile"
    assert "samesite=lax" in r.headers["set-cookie"].lower()
    idp.challenge = query["code_challenge"]
    idp.claims = {"nonce": query["nonce"], **claims}
    state = tamper(query["state"]) if tamper else query["state"]
    return await client.get("/api/auth/oidc/callback", params={"code": "good-code", "state": state})


def error_of(response) -> str:  # type: ignore[no-untyped-def]
    assert response.status_code == 303 and response.headers["location"].startswith("/login?error=")
    return parse_qs(urlsplit(response.headers["location"]).query)["error"][0]


async def test_oidc_sign_in_creates_user_syncs_groups_and_admin(client, session, idp):
    config = (await client.get("/api/auth/config")).json()
    assert config == {"password": True, "oidc": True, "oidc_label": "Single sign-on"}
    claims = {"sub": "u-1", "email": "Carol@Example.com", "email_verified": True, "name": "Carol",
              "groups": ["/doc-readers", "/nb-admins"]}  # fmt: skip
    r = await sign_in(client, idp, claims)
    assert r.status_code == 303 and r.headers["location"] == "/wiki"
    refreshed = await client.post("/api/auth/refresh")
    assert refreshed.status_code == 200, refreshed.text
    me = refreshed.json()["user"]
    assert me["email"] == "carol@example.com" and me["display_name"] == "Carol" and me["is_admin"] is True
    user = await session.scalar(select(User).where(User.email == "carol@example.com"))
    assert user.oidc_subject == "u-1" and user.password_hash is None
    user_id = user.id
    groups = {g.name: g.source for g in (await session.scalars(select(Group))).all()}
    assert groups == {"doc-readers": "oidc", "nb-admins": "oidc"}

    # next sign-in: membership and admin role follow the token; local groups are joined but never left
    local = Group(name="Engineering", source="local")
    session.add(local)
    await session.commit()
    r = await sign_in(client, idp, {**claims, "groups": ["/engineering"]})
    assert r.status_code == 303
    session.expire_all()
    names = set(
        (
            await session.scalars(
                select(Group.name)
                .join(GroupMember, GroupMember.group_id == Group.id)
                .where(GroupMember.user_id == user_id)
            )
        ).all()
    )
    assert names == {"Engineering"}
    assert (await session.get(User, user_id)).is_admin is False


async def test_oidc_links_existing_account_by_verified_email(client, session, idp):
    local_id = (await make_user(session, "dave@example.com")).id
    r = await sign_in(client, idp, {"sub": "u-2", "email": "dave@example.com", "email_verified": True})
    assert r.status_code == 303
    session.expire_all()
    assert (await session.get(User, local_id)).oidc_subject == "u-2"
    # the same email from another identity is refused
    r = await sign_in(client, idp, {"sub": "u-3", "email": "dave@example.com", "email_verified": True})
    assert "another single sign-on identity" in error_of(r)


async def test_oidc_rejections(client, session, idp, monkeypatch):
    good = {"sub": "u-9", "email": "eve@example.com", "email_verified": True}
    assert "does not match" in error_of(await sign_in(client, idp, good, tamper=lambda s: s + "x"))
    idp.overrides = {"nonce": "forged"}
    assert "nonce" in error_of(await sign_in(client, idp, good))
    idp.overrides = {"aud": "another-client"}
    assert "InvalidAudience" in error_of(await sign_in(client, idp, good))
    idp.overrides = {"exp": int(time.time()) - 3600}
    assert "ExpiredSignature" in error_of(await sign_in(client, idp, good))
    idp.overrides = {}
    assert "not verified" in error_of(await sign_in(client, idp, {**good, "email_verified": False}))
    monkeypatch.setattr(get_settings(), "oidc_auto_create_users", False)
    assert "ask an administrator" in error_of(await sign_in(client, idp, good))
    assert await session.scalar(select(User).where(User.email == "eve@example.com")) is None
    # the provider reports an error (e.g. the user cancelled)
    r = await client.get("/api/auth/oidc/callback", params={"error": "access_denied"})
    assert "access_denied" in error_of(r)
    # a callback without the state cookie (e.g. replayed elsewhere)
    client.cookies.clear()
    assert "expired" in error_of(
        await client.get("/api/auth/oidc/callback", params={"code": "c", "state": "s"})
    )


async def test_open_redirect_and_password_mode(client, session, idp, monkeypatch):
    r = await sign_in(
        client,
        idp,
        {"sub": "u-5", "email": "f@example.com", "email_verified": True},
        next_path="//evil.example/x",
    )
    assert r.headers["location"] == "/"
    await make_user(session, "local@example.com")
    monkeypatch.setattr(get_settings(), "auth_mode", "oidc")
    assert (await client.get("/api/auth/config")).json()["password"] is False
    r = await client.post(
        "/api/auth/login", json={"email": "local@example.com", "password": "correct-horse-battery"}
    )
    assert r.status_code == 403
    monkeypatch.setattr(get_settings(), "auth_mode", "local")
    r = await client.get("/api/auth/oidc/login")
    assert "not configured" in error_of(r)
