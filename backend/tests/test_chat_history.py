# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Chat history: all conversations of a user across scopes, search in titles and messages, Markdown export."""

from __future__ import annotations

from tests.conftest import login, make_user
from tests.test_chat import ask, chat, new_conversation  # noqa: F401 - fixtures
from tests.test_sources import embed_calls, jobs, node, world  # noqa: F401 - fixtures


async def test_history_lists_searches_and_exports(client, admin_headers, session, world, chat):
    one = await new_conversation(client, admin_headers, world.wifi["id"])
    await ask(client, admin_headers, one["id"], "How do I restore the factory settings?")
    await ask(client, admin_headers, one["id"], "and for how long?")
    two = await new_conversation(client, admin_headers, world.docs["id"])
    await ask(client, admin_headers, two["id"], "What is the boot sequence?")

    r = await client.get("/api/conversations/history", headers=admin_headers)
    assert r.status_code == 200 and r.headers["X-Total-Count"] == "2"
    items = r.json()
    assert [i["id"] for i in items] == [two["id"], one["id"]]  # most recent first
    first = items[1]
    assert first["scope_name"] == "wifi" and first["message_count"] == 4
    assert first["first_question"] == "How do I restore the factory settings?"

    # search looks in titles and in the text of every message, and says where it matched
    r = await client.get("/api/conversations/history", headers=admin_headers, params={"q": "factory"})
    found = r.json()
    assert [i["id"] for i in found] == [one["id"]] and "factory" in found[0]["match"].lower()
    assert (
        await client.get("/api/conversations/history", headers=admin_headers, params={"q": "100%_"})
    ).json() == []

    # filtered to a scope (and what is below it)
    r = await client.get(
        "/api/conversations/history", headers=admin_headers, params={"scope_id": world.docs["id"]}
    )
    assert [i["id"] for i in r.json()] == [two["id"]]

    export = await client.get(f"/api/conversations/{one['id']}/export", headers=admin_headers)
    assert export.status_code == 200 and export.headers["content-type"].startswith("text/markdown")
    assert "attachment" in export.headers["content-disposition"]
    assert export.text.startswith("# How do I restore the factory settings?")
    assert "## and for how long?" in export.text and "Sources:" in export.text and "manual.pdf" in export.text


async def test_history_is_private_and_follows_access(client, admin_headers, session, world, chat):
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    await ask(client, admin_headers, conv["id"], "How do I restore the factory settings?")
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    assert (await client.get("/api/conversations/history", headers=bob_headers)).json() == []
    await client.put(
        f"/api/nodes/{world.wifi['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    # bob can read the scope but the conversation is the admin's
    assert (await client.get("/api/conversations/history", headers=bob_headers)).json() == []
    assert (
        await client.get(f"/api/conversations/{conv['id']}/export", headers=bob_headers)
    ).status_code == 404
    secret = await node(client, admin_headers, "project", "secret")
    unreadable = await client.get(
        "/api/conversations/history", headers=bob_headers, params={"scope_id": secret["id"]}
    )
    assert unreadable.status_code == 404
