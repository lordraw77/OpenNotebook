# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""M5 administration: groups (US-07), provider policy per project, zero-downtime embedding change (US-08),
administrator reset."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from opennotebook.ingestion.vectors import collection_for, get_vector_index
from opennotebook.models import Chunk, ProjectSettings, RefreshToken
from tests.conftest import login, make_user
from tests.test_chat import FakeChat, chat, new_conversation  # noqa: F401 - fixtures
from tests.test_sources import (  # noqa: F401 - fixtures
    RADIO_MD,
    embed_calls,
    jobs,
    run_jobs,
    search,
    upload,
    world,
)


async def ask(client, headers, conv_id, question) -> list[tuple[str, dict]]:
    r = await client.post(
        f"/api/conversations/{conv_id}/messages", headers=headers, json={"content": question}
    )
    assert r.status_code == 200, r.text
    out = []
    for block in r.text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


# --- groups / US-07 -------------------------------------------------------------------------------------


async def test_group_administration(client, admin_headers, session):
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    r = await client.post(
        "/api/groups", headers=admin_headers, json={"name": "Readers", "description": "docs"}
    )
    assert r.status_code == 201, r.text
    group = r.json()
    assert (
        await client.post("/api/groups", headers=admin_headers, json={"name": "readers"})
    ).status_code == 409
    assert (await client.post("/api/groups", headers=bob_headers, json={"name": "x"})).status_code == 403
    assert (
        await client.put(f"/api/groups/{group['id']}/members/{bob.id}", headers=admin_headers)
    ).status_code == 204
    members = (await client.get(f"/api/groups/{group['id']}/members", headers=admin_headers)).json()
    assert [m["email"] for m in members] == ["bob@example.com"]
    assert (await client.get("/api/groups", headers=admin_headers)).json()[0]["members"] == 1
    # any user can find a group to share with, without seeing its members
    found = (await client.get("/api/groups/directory", headers=bob_headers, params={"q": "read"})).json()
    assert [g["name"] for g in found] == ["Readers"] and "members" not in found[0] or found[0]["members"] == 0
    assert (await client.get(f"/api/groups/{group['id']}/members", headers=bob_headers)).status_code == 403
    r = await client.patch(f"/api/groups/{group['id']}", headers=admin_headers, json={"name": "Doc readers"})
    assert r.json()["name"] == "Doc readers"
    assert (await client.delete(f"/api/groups/{group['id']}", headers=admin_headers)).status_code == 204
    assert (await client.get("/api/groups", headers=admin_headers)).json() == []


async def test_us07_group_reads_documentation_but_never_source(client, admin_headers, session, world, chat):
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    group = (await client.post("/api/groups", headers=admin_headers, json={"name": "doc-readers"})).json()
    await client.put(f"/api/groups/{group['id']}/members/{bob.id}", headers=admin_headers)
    r = await client.put(
        f"/api/nodes/{world.docs['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "group", "principal_id": group["id"], "role": "viewer"},
    )
    assert r.status_code == 200, r.text
    grants = (await client.get(f"/api/nodes/{world.docs['id']}/grants", headers=admin_headers)).json()
    assert any(g["principal_type"] == "group" and g["principal_name"] == "doc-readers" for g in grants)

    # the tree shows the project (for navigation) and docs, never `source`
    names = {n["name"] for n in (await client.get("/api/nodes", headers=bob_headers)).json()}
    assert "docs" in names and "manuals" in names and "source" not in names and "driver" not in names
    # a chat on the whole project never cites `source`
    conv = await new_conversation(client, bob_headers, world.wifi["id"])
    events = await ask(client, bob_headers, conv["id"], "radio driver channel transmit power reset button")
    context = next(d for k, d in events if k == "sources")["context"]
    assert context and {c["source_title"] for c in context} == {"manual.pdf"}
    # the chat model selector works with access to a subtree only
    r = await client.get(
        "/api/models/selectable",
        headers=bob_headers,
        params={"phase": "chat", "project_id": world.wifi["id"]},
    )
    assert r.status_code == 200 and [m["model"] for m in r.json()][:2] == ["chat-a", "chat-b"]
    assert (await client.get(f"/api/nodes/{world.src['id']}/grants", headers=bob_headers)).status_code == 404
    # leaving the group removes the access
    await client.delete(f"/api/groups/{group['id']}/members/{bob.id}", headers=admin_headers)
    assert (
        await client.post(
            "/api/search", headers=bob_headers, json={"scope_id": world.docs["id"], "query": "reset"}
        )
    ).status_code == 404


# --- provider policy -------------------------------------------------------------------------------------


async def test_provider_policy_restricts_every_model_call(client, admin_headers, session, world, chat):
    settings = (await client.get(f"/api/projects/{world.wifi['id']}/settings", headers=admin_headers)).json()
    providers = {p["name"]: p for p in settings["providers"]}
    assert (
        settings["restricted"] is False and providers["groq"]["allowed"] and providers["mistral"]["allowed"]
    )

    # only Mistral (embeddings): the chat chain (Groq) is blocked, search still works
    r = await client.put(
        f"/api/projects/{world.wifi['id']}/policy",
        headers=admin_headers,
        json={"allowed_provider_ids": [providers["mistral"]["id"]]},
    )
    assert r.status_code == 200 and r.json()["restricted"] is True
    assert {p["name"] for p in r.json()["providers"] if p["allowed"]} == {"mistral"}
    assert await search(client, admin_headers, world.wifi["id"], "reset button")
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    events = await ask(client, admin_headers, conv["id"], "How do I reset?")
    assert "provider policy" in next(d for k, d in events if k == "error")["message"]
    assert chat.fake.calls == []
    selectable = (
        await client.get(
            "/api/models/selectable",
            headers=admin_headers,
            params={"phase": "chat", "project_id": world.wifi["id"]},
        )
    ).json()
    assert selectable == []
    # an explicitly selected model of a blocked provider is refused too
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=admin_headers,
        json={"content": "hi", "model_id": chat.models["chat-a"]},
    )
    assert "provider policy" in r.text

    # nothing allowed: even embeddings are refused
    await client.put(
        f"/api/projects/{world.wifi['id']}/policy", headers=admin_headers, json={"allowed_provider_ids": []}
    )
    r = await client.post(
        "/api/search", headers=admin_headers, json={"scope_id": world.wifi["id"], "query": "reset"}
    )
    assert r.status_code == 503 and "provider policy" in r.json()["detail"]

    # owners only; null lifts the restriction
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    await client.put(
        f"/api/nodes/{world.wifi['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "editor"},
    )
    r = await client.put(
        f"/api/projects/{world.wifi['id']}/policy", headers=bob_headers, json={"allowed_provider_ids": None}
    )
    assert r.status_code == 403
    await client.put(
        f"/api/projects/{world.wifi['id']}/policy", headers=admin_headers, json={"allowed_provider_ids": None}
    )
    events = await ask(client, admin_headers, conv["id"], "How do I reset the device?")
    assert next(d for k, d in events if k == "done")["status"] == "complete"


# --- US-08: zero-downtime embedding change ------------------------------------------------------------------


async def test_us08_embedding_change_keeps_search_live_until_atomic_switch(
    client, admin_headers, session, world, embed_calls, jobs
):
    models = {
        m["model"]: m["id"]
        for m in (
            await client.get(
                "/api/models/selectable",
                headers=admin_headers,
                params={"phase": "embedding", "include_all": True},
            )
        ).json()
    }
    project_id = uuid.UUID(world.wifi["id"])
    row = await session.get(ProjectSettings, project_id)
    old_model = uuid.UUID(models["mistral-embed"])
    assert row.embedding_model_id == old_model
    chunk_ids_before = set((await session.scalars(select(Chunk.id))).all())
    index = get_vector_index()
    old_count = await index.count(collection_for(old_model))
    assert old_count > 0

    # the administrator changes the embedding model
    r = await client.put(
        "/api/model-assignments/embedding", headers=admin_headers, json={"model_ids": [models["other-embed"]]}
    )
    assert r.status_code == 200
    status = (await client.get(f"/api/projects/{project_id}/settings", headers=admin_headers)).json()["index"]
    assert status["switch_pending"] is True and status["serving_model"] == "mistral/mistral-embed"

    # searches keep using the old index (query embedded with the old model) and find everything
    embed_calls.clear()
    assert {
        h["source_title"]
        for h in await search(client, admin_headers, world.wifi["id"], "radio channel reset button")
    } == {"radio.md", "manual.pdf"}
    assert [c["model"] for c in embed_calls] == ["mistral/mistral-embed"]

    # a source added during the change is embedded with the new model only, and searchable right away
    embed_calls.clear()
    await upload(
        client,
        admin_headers,
        world.manuals["id"],
        [("extra.md", b"# Extra\n\nThe antenna gain is five dBi.\n")],
    )
    await run_jobs(session, jobs)
    assert {c["model"] for c in embed_calls} == {"mistral/other-embed"}  # never embedded twice
    embed_calls.clear()
    assert "extra.md" in {
        h["source_title"] for h in await search(client, admin_headers, world.wifi["id"], "antenna gain dBi")
    }
    # the search embeds the query with both models and fuses the two indexes
    assert {c["model"] for c in embed_calls} == {"mistral/other-embed", "mistral/mistral-embed"}

    # re-index: after the first source the old index still serves everything
    r = await client.post(f"/api/ingestion/projects/{project_id}/reindex", headers=admin_headers)
    assert r.json()["queued"] == 3
    first = [j for j in jobs if j[0] == "ingest"][0]
    jobs.remove(first)
    embed_calls.clear()
    await run_jobs(session, [first])
    assert {c["model"] for c in embed_calls} == {"mistral/other-embed"}
    session.expire_all()
    assert (await session.get(ProjectSettings, project_id)).embedding_model_id == old_model
    titles = {
        h["source_title"]
        for h in await search(client, admin_headers, world.wifi["id"], "radio channel reset button antenna")
    }
    assert titles == {"radio.md", "manual.pdf", "extra.md"}

    # the last source completes the re-index: atomic switch, old vectors removed
    await run_jobs(session, [j for j in jobs if j[0] == "ingest"])
    session.expire_all()
    row = await session.get(ProjectSettings, project_id)
    assert row.embedding_model_id == uuid.UUID(models["other-embed"]) and row.index_switched_at is not None
    assert await index.count(collection_for(old_model)) == 0
    embed_calls.clear()
    assert {
        h["source_title"]
        for h in await search(client, admin_headers, world.wifi["id"], "radio channel reset button antenna")
    } == {"radio.md", "manual.pdf", "extra.md"}
    assert [c["model"] for c in embed_calls] == ["mistral/other-embed"]
    # deterministic chunk ids: re-indexing unchanged content kept the ids (citations stay valid)
    assert chunk_ids_before <= set((await session.scalars(select(Chunk.id))).all())
    status = (await client.get(f"/api/projects/{project_id}/settings", headers=admin_headers)).json()["index"]
    assert status["switch_pending"] is False and status["sources_on_configured_model"] == 3


# --- administrator reset ------------------------------------------------------------------------------------


async def test_reset_admin_creates_or_resets_and_revokes_sessions(client, session):
    from opennotebook.cli import reset_admin

    assert await reset_admin("Root@Example.com", "a-long-new-password") == "created"
    headers = await login(client, "root@example.com", "a-long-new-password")
    assert (await client.get("/api/auth/me", headers=headers)).json()["is_admin"] is True
    assert await session.scalar(select(RefreshToken.id)) is not None
    assert await reset_admin("root@example.com", "another-long-password") == "reset"
    session.expire_all()
    assert await session.scalar(select(RefreshToken.id)) is None
    r = await client.post(
        "/api/auth/login", json={"email": "root@example.com", "password": "a-long-new-password"}
    )
    assert r.status_code == 401
    await login(client, "root@example.com", "another-long-password")
