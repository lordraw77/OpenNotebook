# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Graph editor: rename, retype, merge, delete, manual relations; edits survive a re-index, respect roles."""

from __future__ import annotations

from tests.conftest import login, make_user
from tests.test_m4 import get_entities, kg  # noqa: F401 - fixtures
from tests.test_sources import embed_calls, jobs, run_jobs  # noqa: F401 - fixtures


def q(kg):
    return {"scope_id": kg.wifi["id"]}


async def graph_edges(client, headers, kg) -> set[tuple[str, str, str]]:
    g = (await client.get("/api/graph", headers=headers, params=q(kg))).json()
    by_id = {n["id"]: n["name"] for n in g["nodes"]}
    return {(by_id[e["source"]], e["type"], by_id[e["target"]]) for e in g["edges"]}


async def test_rename_retype_and_survive_reindex(client, admin_headers, session, kg, jobs):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    wpa = names["WPA3"]["id"]
    r = await client.patch(
        f"/api/entities/{wpa}",
        headers=admin_headers,
        params=q(kg),
        json={"name": "WPA3 (Wi-Fi)", "type": "technology"},
    )
    assert r.status_code == 200 and r.json()["name"] == "WPA3 (Wi-Fi)" and r.json()["type"] == "technology"
    bad = await client.patch(
        f"/api/entities/{wpa}", headers=admin_headers, params=q(kg), json={"type": "spaceship"}
    )
    assert bad.status_code == 422
    await client.post(f"/api/ingestion/projects/{kg.wifi['id']}/graph", headers=admin_headers)
    await run_jobs(session, jobs)
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    assert "WPA3 (Wi-Fi)" in names and names["WPA3 (Wi-Fi)"]["type"] == "technology" and "WPA3" not in names


async def test_merge_follows_future_extractions(client, admin_headers, session, kg, jobs):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    driver, ap = names["Radio driver"]["id"], names["Access point"]["id"]
    r = await client.post(
        f"/api/entities/{ap}/merge", headers=admin_headers, params=q(kg), json={"target_id": driver}
    )
    assert r.status_code == 200 and r.json()["name"] == "Radio driver"
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    assert set(names) == {"Radio driver", "WPA3"} and names["Radio driver"]["sources"] == 2
    assert await graph_edges(client, admin_headers, kg) == {
        ("Radio driver", "uses", "WPA3"),
        ("Radio driver", "supports", "WPA3"),
    }
    # the manual is indexed again: "Access point" mentions land on the merge target, not on a new entity
    await client.post(f"/api/ingestion/projects/{kg.wifi['id']}/graph", headers=admin_headers)
    await run_jobs(session, jobs)
    assert set(await get_entities(client, admin_headers, kg.wifi["id"])) == {"Radio driver", "WPA3"}
    same = await client.post(
        f"/api/entities/{driver}/merge", headers=admin_headers, params=q(kg), json={"target_id": driver}
    )
    assert same.status_code == 422


async def test_deleted_entity_and_relation_stay_deleted(client, admin_headers, session, kg, jobs):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    detail = (
        await client.get(f"/api/entities/{names['Radio driver']['id']}", headers=admin_headers, params=q(kg))
    ).json()
    [rel] = detail["related"]
    assert (
        await client.delete(f"/api/relations/{rel['relation_id']}", headers=admin_headers, params=q(kg))
    ).status_code == 204
    assert await graph_edges(client, admin_headers, kg) == {("Access point", "supports", "WPA3")}
    assert (
        await client.delete(
            f"/api/entities/{names['Access point']['id']}", headers=admin_headers, params=q(kg)
        )
    ).status_code == 204
    gone = await client.get(
        f"/api/entities/{names['Access point']['id']}", headers=admin_headers, params=q(kg)
    )
    assert gone.status_code == 404
    await client.post(f"/api/ingestion/projects/{kg.wifi['id']}/graph", headers=admin_headers)
    await run_jobs(session, jobs)
    assert set(await get_entities(client, admin_headers, kg.wifi["id"])) == {"Radio driver", "WPA3"}
    assert await graph_edges(client, admin_headers, kg) == set()


async def test_manual_relation_is_kept_and_visibility_still_applies(client, admin_headers, session, kg, jobs):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    body = {
        "scope_id": kg.wifi["id"],
        "source_id": names["Access point"]["id"],
        "target_id": names["Radio driver"]["id"],
        "type": "Depends On",
        "description": "Known from the design review.",
    }
    r = await client.post("/api/relations", headers=admin_headers, json=body)
    assert r.status_code == 201 and r.json()["type"] == "depends_on"
    assert (await client.post("/api/relations", headers=admin_headers, json=body)).status_code == 422
    assert ("Access point", "depends_on", "Radio driver") in await graph_edges(client, admin_headers, kg)
    await client.post(f"/api/ingestion/projects/{kg.wifi['id']}/graph", headers=admin_headers)
    await run_jobs(session, jobs)
    assert ("Access point", "depends_on", "Radio driver") in await graph_edges(client, admin_headers, kg)
    # hiding the manual's source hides the entity and so the relation
    await client.patch(f"/api/sources/{kg.manual['id']}", headers=admin_headers, json={"active": False})
    assert await graph_edges(client, admin_headers, kg) == {("Radio driver", "uses", "WPA3")}


async def test_editing_needs_the_editor_role(client, admin_headers, session, kg):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    bob = await make_user(session, "bob@example.com")
    r = await client.put(
        f"/api/nodes/{kg.wifi['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    assert r.status_code in (200, 201), r.text
    headers = await login(client, "bob@example.com")
    wpa = names["WPA3"]["id"]
    assert (await client.get(f"/api/entities/{wpa}", headers=headers, params=q(kg))).status_code == 200
    denied = await client.patch(f"/api/entities/{wpa}", headers=headers, params=q(kg), json={"name": "x"})
    assert denied.status_code == 403
    assert (await client.delete(f"/api/entities/{wpa}", headers=headers, params=q(kg))).status_code == 403
