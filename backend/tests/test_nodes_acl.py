from __future__ import annotations

from sqlalchemy import select

from tests.conftest import login, make_user


async def create(client, headers, kind, name, parent=None):
    resp = await client.post(
        "/api/nodes", headers=headers, json={"kind": kind, "name": name, "parent_id": parent}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_free_nesting_and_kind_rules(client, alice_headers):
    wifi = await create(client, alice_headers, "project", "wifi")
    assert wifi["role"] == "owner"
    source = await create(client, alice_headers, "workspace", "source", wifi["id"])
    modules = await create(client, alice_headers, "workspace", "modules", source["id"])
    driver = await create(client, alice_headers, "notebook", "driver", modules["id"])
    radio = await create(client, alice_headers, "notebook", "radio", driver["id"])
    assert radio["depth"] == 4
    assert radio["project_id"] == wifi["id"]

    bad = await client.post(
        "/api/nodes", headers=alice_headers, json={"kind": "workspace", "name": "x", "parent_id": radio["id"]}
    )
    assert bad.status_code == 422  # a workspace cannot live under a notebook
    no_parent = await client.post("/api/nodes", headers=alice_headers, json={"kind": "notebook", "name": "x"})
    assert no_parent.status_code == 422
    dup = await client.post(
        "/api/nodes",
        headers=alice_headers,
        json={"kind": "workspace", "name": "Source", "parent_id": wifi["id"]},
    )
    assert dup.status_code == 409


async def test_move_updates_subtree_and_rejects_cycles(client, alice_headers, session):
    from opennotebook.models import Node

    p = await create(client, alice_headers, "project", "p")
    a = await create(client, alice_headers, "workspace", "a", p["id"])
    b = await create(client, alice_headers, "workspace", "b", p["id"])
    nb = await create(client, alice_headers, "notebook", "nb", a["id"])
    leaf = await create(client, alice_headers, "notebook", "leaf", nb["id"])

    moved = await client.patch(f"/api/nodes/{nb['id']}", headers=alice_headers, json={"parent_id": b["id"]})
    assert moved.status_code == 200, moved.text
    rows = {n.name: n for n in (await session.scalars(select(Node))).all()}
    assert rows["leaf"].path.startswith(rows["b"].path + ".")
    assert rows["leaf"].depth == leaf["depth"]  # same level: a and b are siblings

    cycle = await client.patch(f"/api/nodes/{b['id']}", headers=alice_headers, json={"parent_id": leaf["id"]})
    assert cycle.status_code == 422

    other = await create(client, alice_headers, "project", "other")
    cross = await client.patch(
        f"/api/nodes/{nb['id']}", headers=alice_headers, json={"parent_id": other["id"]}
    )
    assert cross.status_code == 422


async def test_switch_and_delete_cascade(client, alice_headers):
    p = await create(client, alice_headers, "project", "p2")
    w = await create(client, alice_headers, "workspace", "w", p["id"])
    n = await create(client, alice_headers, "notebook", "n", w["id"])

    off = await client.patch(f"/api/nodes/{w['id']}", headers=alice_headers, json={"active": False})
    assert off.json()["active"] is False
    assert (await client.get(f"/api/nodes/{n['id']}", headers=alice_headers)).json()["active"] is False

    assert (await client.delete(f"/api/nodes/{w['id']}", headers=alice_headers)).status_code == 204
    assert (await client.get(f"/api/nodes/{n['id']}", headers=alice_headers)).status_code == 404
    # the name is free again
    await create(client, alice_headers, "workspace", "w", p["id"])


async def test_grants_inheritance_and_visibility(client, session, alice_headers):
    from opennotebook.acl import readable_subtree_roots
    from opennotebook.models import Node, User

    wifi = await create(client, alice_headers, "project", "wifi")
    docs = await create(client, alice_headers, "workspace", "documentation", wifi["id"])
    src = await create(client, alice_headers, "workspace", "source", wifi["id"])
    manuals = await create(client, alice_headers, "notebook", "manuals", docs["id"])

    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    # Before any grant Bob sees nothing and gets 404 (no existence leak).
    assert (await client.get("/api/nodes", headers=bob_headers)).json() == []
    assert (await client.get(f"/api/nodes/{docs['id']}", headers=bob_headers)).status_code == 404

    grant = await client.put(
        f"/api/nodes/{docs['id']}/grants",
        headers=alice_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    assert grant.status_code == 200

    visible = {n["name"]: n["role"] for n in (await client.get("/api/nodes", headers=bob_headers)).json()}
    assert visible == {"wifi": None, "documentation": "viewer", "manuals": "viewer"}
    assert (await client.get(f"/api/nodes/{src['id']}", headers=bob_headers)).status_code == 404
    # viewer cannot create inside
    denied = await client.post(
        "/api/nodes", headers=bob_headers, json={"kind": "notebook", "name": "x", "parent_id": manuals["id"]}
    )
    assert denied.status_code == 403

    # Retrieval pre-filter: a search on the project is limited to the documentation subtree.
    bob_row = await session.get(User, bob.id)
    project = await session.get(Node, wifi["id"])
    docs_row = await session.get(Node, docs["id"])
    assert await readable_subtree_roots(session, bob_row, project) == [docs_row.path]
    assert await readable_subtree_roots(session, bob_row, docs_row) is None


async def test_last_project_owner_cannot_be_removed(client, session, alice_headers):
    p = await create(client, alice_headers, "project", "solo")
    me = (await client.get("/api/auth/me", headers=alice_headers)).json()
    resp = await client.delete(f"/api/nodes/{p['id']}/grants/user/{me['id']}", headers=alice_headers)
    assert resp.status_code == 409
