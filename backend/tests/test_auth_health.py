from __future__ import annotations

from tests.conftest import login, make_user


async def test_live(client):
    resp = await client.get("/api/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


async def test_ready_reports_components(client):
    resp = await client.get("/api/health/ready")
    names = {c["name"] for c in resp.json()["components"]}
    assert names == {"postgres", "redis", "qdrant", "storage"}
    pg = next(c for c in resp.json()["components"] if c["name"] == "postgres")
    assert pg["ok"] is True


async def test_login_me_and_wrong_password(client, session):
    await make_user(session, "bob@example.com")
    bad = await client.post("/api/auth/login", json={"email": "bob@example.com", "password": "nope"})
    assert bad.status_code == 401
    headers = await login(client, "bob@example.com")
    me = await client.get("/api/auth/me", headers=headers)
    assert me.json()["email"] == "bob@example.com"
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_refresh_rotation_and_reuse_detection(client, session):
    await make_user(session, "carol@example.com")
    await login(client, "carol@example.com")
    first = client.cookies.get("on_refresh")
    assert first

    rotated = await client.post("/api/auth/refresh")
    assert rotated.status_code == 200
    second = client.cookies.get("on_refresh")
    assert second and second != first

    # Replaying the first (rotated) token revokes all sessions.
    client.cookies.set("on_refresh", first, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401
    client.cookies.set("on_refresh", second, path="/api/auth")
    assert (await client.post("/api/auth/refresh")).status_code == 401


async def test_user_admin_endpoints_require_admin(client, alice_headers, admin_headers):
    assert (await client.get("/api/users", headers=alice_headers)).status_code == 403
    created = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"email": "dave@example.com", "display_name": "Dave", "password": "a-long-password-1"},
    )
    assert created.status_code == 201
    dup = await client.post(
        "/api/users",
        headers=admin_headers,
        json={"email": "DAVE@example.com", "display_name": "Dave", "password": "a-long-password-1"},
    )
    assert dup.status_code == 409
