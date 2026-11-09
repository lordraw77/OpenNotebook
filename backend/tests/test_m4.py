# ruff: noqa: F811 - fixtures imported from test_sources are redefined as parameters
"""M4 knowledge graph and wiki: extraction (code without a model, documents with a scripted model),
visibility (ACL, switches, scope), wiki pages from visible passages, graph expansion in the chat."""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

import litellm
import pytest

from opennotebook.graph.extract import parse_graph_reply
from opennotebook.graph.store import canonical, entity_type
from opennotebook.models import ModelPhase, SourceStatus
from opennotebook.providers import service
from opennotebook.providers.catalog import DiscoveredModel
from tests.conftest import login, make_user
from tests.test_m3 import make_zip
from tests.test_sources import (  # noqa: F401 - fixtures
    embed_calls,
    jobs,
    node,
    run_jobs,
    setup_embedding,
    upload,
)


def test_canonical_names_and_types():
    assert canonical("  The WPA3 ") == canonical("wpa3") == "wpa3"
    assert canonical("Il Driver  Radio") == "driver radio"
    assert canonical("“Access Point”.") == "access point"
    assert entity_type("Standard") == "standard" and entity_type("spaceship") == "concept"
    entities, relations = parse_graph_reply(
        'ok {"entities": [{"name": "A"}, {"name": ""}], "relations": [1, {}]}'
    )
    assert [e["name"] for e in entities] == ["A"] and relations == [{}]


RADIO_MD = (
    b"# Radio driver\n\nThe radio driver encrypts every frame with WPA3 before transmission on the channel.\n"
)
MANUAL_MD = b"# Access point manual\n\nThe access point supports WPA3 and must be reset with the button.\n"

GRAPHS = {
    "radio driver": {
        "entities": [
            {"name": "Radio driver", "type": "component", "description": "Encrypts frames.", "passages": [1]},
            {"name": "WPA3", "type": "standard", "description": "Used by the radio driver.", "passages": [1]},
        ],
        "relations": [{"source": "Radio driver", "target": "WPA3", "type": "uses", "passage": 1}],
    },
    "access point": {
        "entities": [
            {"name": "Access point", "type": "product", "description": "Supports WPA3.", "passages": [1]},
            {"name": "the WPA3", "type": "standard", "description": "Supported by the AP.", "passages": [1]},
        ],
        "relations": [{"source": "Access point", "target": "the WPA3", "type": "supports", "passage": 1}],
    },
}


class FakeLLM:
    def __init__(self) -> None:
        self.prompts: list[tuple[str, str]] = []

    async def __call__(self, model, messages, stream=False, **kwargs):
        prompt = messages[-1]["content"]
        if prompt.startswith("Extract a knowledge graph"):
            kind = "graph"
            key = "radio driver" if "radio driver encrypts" in prompt else "access point"
            text = json.dumps(GRAPHS[key])
        elif prompt.startswith("Write a short wiki article"):
            kind, text = "wiki", "WPA3 is a security standard [S1]. It is widely used [S1][S7]."
        else:
            kind, text = "chat", "WPA3 protects the frames [S1]."
        self.prompts.append((kind, prompt))
        if not stream:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])

        async def gen():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)

        return gen()


@pytest.fixture
async def kg(client, admin_headers, session, embed_calls, jobs, monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(litellm, "acompletion", fake)

    async def catalog(kind, **_):
        return [
            DiscoveredModel("mistral-embed", capabilities={ModelPhase.embedding}, source="provider"),
            DiscoveredModel("mistral-large", capabilities={ModelPhase.chat}, source="provider"),
        ]

    monkeypatch.setattr(service, "list_models", catalog)
    models = await setup_embedding(client, admin_headers)
    for phase in ("graph_extraction", "summary", "chat"):
        r = await client.put(
            f"/api/model-assignments/{phase}",
            headers=admin_headers,
            json={"model_ids": [models["mistral-large"]]},
        )
        assert r.status_code == 200, r.text
    wifi = await node(client, admin_headers, "project", "wifi")
    src = await node(client, admin_headers, "workspace", "source", wifi["id"])
    docs = await node(client, admin_headers, "workspace", "docs", wifi["id"])
    driver = await node(client, admin_headers, "notebook", "driver", src["id"])
    manuals = await node(client, admin_headers, "notebook", "manuals", docs["id"])
    [radio] = await upload(client, admin_headers, driver["id"], [("radio.md", RADIO_MD)])
    [manual] = await upload(client, admin_headers, manuals["id"], [("manual.md", MANUAL_MD)])
    assert await run_jobs(session, jobs) == [SourceStatus.ready, SourceStatus.ready]
    return SimpleNamespace(
        fake=fake, wifi=wifi, src=src, docs=docs, driver=driver, manuals=manuals,
        radio=radio["source"], manual=manual["source"],
    )  # fmt: skip


async def get_entities(client, headers, scope_id, **params) -> dict[str, dict]:
    r = await client.get("/api/entities", headers=headers, params={"scope_id": scope_id, **params})
    assert r.status_code == 200, r.text
    return {e["name"]: e for e in r.json()}


async def test_document_graph_merges_entities_across_sources(client, admin_headers, kg):
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    assert set(names) == {"Radio driver", "WPA3", "Access point"}
    assert names["WPA3"]["sources"] == 2 and names["WPA3"]["type"] == "standard"
    src = (await client.get(f"/api/sources/{kg.radio['id']}", headers=admin_headers)).json()
    assert src["graph_status"] == "done"

    graph = (await client.get("/api/graph", headers=admin_headers, params={"scope_id": kg.wifi["id"]})).json()
    by_id = {n["id"]: n["name"] for n in graph["nodes"]}
    edges = {(by_id[e["source"]], e["type"], by_id[e["target"]]) for e in graph["edges"]}
    assert edges == {("Radio driver", "uses", "WPA3"), ("Access point", "supports", "WPA3")}

    detail = (
        await client.get(
            f"/api/entities/{names['WPA3']['id']}", headers=admin_headers, params={"scope_id": kg.wifi["id"]}
        )
    ).json()
    assert detail["mention_count"] == 2 and {m["source_title"] for m in detail["mentions"]} == {
        "radio.md",
        "manual.md",
    }
    assert {(r["name"], r["relation"], r["direction"]) for r in detail["related"]} == {
        ("Radio driver", "uses", "in"),
        ("Access point", "supports", "in"),
    }
    # the scope limits the graph too
    assert set(await get_entities(client, admin_headers, kg.docs["id"])) == {"WPA3", "Access point"}
    assert set(await get_entities(client, admin_headers, kg.wifi["id"], q="radio")) == {"Radio driver"}


async def test_graph_never_leaks_unreadable_sources(client, admin_headers, session, kg):
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    await client.put(
        f"/api/nodes/{kg.docs['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    names = await get_entities(client, bob_headers, kg.wifi["id"])
    assert set(names) == {"WPA3", "Access point"} and names["WPA3"]["sources"] == 1
    admin_names = await get_entities(client, admin_headers, kg.wifi["id"])
    hidden = admin_names["Radio driver"]["id"]
    r = await client.get(f"/api/entities/{hidden}", headers=bob_headers, params={"scope_id": kg.wifi["id"]})
    assert r.status_code == 404
    detail = (
        await client.get(
            f"/api/entities/{names['WPA3']['id']}", headers=bob_headers, params={"scope_id": kg.wifi["id"]}
        )
    ).json()
    assert [m["source_title"] for m in detail["mentions"]] == ["manual.md"]
    assert [r["name"] for r in detail["related"]] == ["Access point"]
    assert detail["descriptions"] == ["Supported by the AP."]
    graph = (await client.get("/api/graph", headers=bob_headers, params={"scope_id": kg.wifi["id"]})).json()
    assert {n["name"] for n in graph["nodes"]} == {"WPA3", "Access point"} and len(graph["edges"]) == 1
    r = await client.get("/api/entities", headers=bob_headers, params={"scope_id": kg.src["id"]})
    assert r.status_code == 404

    # the wiki page bob gets is written only from what bob can read, and cached separately
    wiki_bob = await client.post(
        f"/api/entities/{names['WPA3']['id']}/wiki", headers=bob_headers, params={"scope_id": kg.wifi["id"]}
    )
    assert wiki_bob.status_code == 200, wiki_bob.text
    prompt = [p for k, p in kg.fake.prompts if k == "wiki"][-1]
    assert "access point supports WPA3" in prompt and "radio driver" not in prompt.lower()
    page = wiki_bob.json()
    assert page["body_md"] == "WPA3 is a security standard [S1]. It is widely used [S1]."
    assert [c["source_title"] for c in page["citations"]] == ["manual.md"] and page["cached"] is False
    again = await client.post(
        f"/api/entities/{names['WPA3']['id']}/wiki", headers=bob_headers, params={"scope_id": kg.wifi["id"]}
    )
    assert again.json()["cached"] is True
    wiki_admin = await client.post(
        f"/api/entities/{names['WPA3']['id']}/wiki", headers=admin_headers, params={"scope_id": kg.wifi["id"]}
    )
    assert wiki_admin.json()["cached"] is False  # different visible passages -> different page
    assert len([k for k, _ in kg.fake.prompts if k == "wiki"]) == 2


async def test_switches_and_deletion_update_the_graph(client, admin_headers, session, kg, jobs):
    await client.patch(f"/api/sources/{kg.manual['id']}", headers=admin_headers, json={"active": False})
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    assert set(names) == {"Radio driver", "WPA3"} and names["WPA3"]["sources"] == 1
    await client.patch(f"/api/sources/{kg.manual['id']}", headers=admin_headers, json={"active": True})
    await client.patch(f"/api/nodes/{kg.src['id']}", headers=admin_headers, json={"active": False})
    assert set(await get_entities(client, admin_headers, kg.wifi["id"])) == {"WPA3", "Access point"}
    await client.patch(f"/api/nodes/{kg.src['id']}", headers=admin_headers, json={"active": True})

    assert (await client.delete(f"/api/sources/{kg.manual['id']}", headers=admin_headers)).status_code == 204
    await run_jobs(session, jobs)  # purge
    names = await get_entities(client, admin_headers, kg.wifi["id"])
    assert set(names) == {"Radio driver", "WPA3"}
    from sqlalchemy import func, select

    from opennotebook.models import Entity

    assert (
        await session.scalar(select(func.count()).select_from(Entity)) == 2
    )  # orphan "Access point" removed


async def test_chat_context_is_expanded_through_the_graph(client, admin_headers, kg, monkeypatch):
    from opennotebook.config import get_settings

    monkeypatch.setattr(get_settings(), "chat_context_chunks", 1)
    conv = (
        await client.post("/api/conversations", headers=admin_headers, json={"scope_id": kg.wifi["id"]})
    ).json()
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=admin_headers,
        json={"content": "How does the radio driver encrypt frames before transmission?"},
    )
    events = [
        (b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1])) for b in r.text.strip().split("\n\n")
    ]
    context = next(d for k, d in events if k == "sources")["context"]
    assert [(c["source_title"], c["via"]) for c in context] == [
        ("radio.md", "search"),
        ("manual.md", "graph"),
    ]

    # in a scope that excludes the neighbour's source, expansion adds nothing
    conv = (
        await client.post("/api/conversations", headers=admin_headers, json={"scope_id": kg.src["id"]})
    ).json()
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=admin_headers,
        json={"content": "How does the radio driver encrypt frames before transmission?"},
    )
    context = json.loads(re.search(r"event: sources\ndata: (.*)", r.text).group(1))["context"]
    assert [c["source_title"] for c in context] == ["radio.md"]


A_PY = b"""from b import helper


class Radio:
    def set_channel(self, ch):
        return helper(ch)


def main():
    Radio().set_channel(1)
"""
B_PY = b"""def helper(x):
    return x * 2
"""


async def test_code_graph_without_a_model(client, admin_headers, session, kg, jobs):
    archive = make_zip({"pkg/a.py": A_PY, "pkg/b.py": B_PY})
    await upload(client, admin_headers, kg.driver["id"], [("pkg.zip", archive)])
    await run_jobs(session, jobs)
    calls_before = len(kg.fake.prompts)
    await run_jobs(session, jobs)
    assert len(kg.fake.prompts) == calls_before  # code needs no model
    graph = (
        await client.get("/api/graph", headers=admin_headers, params={"scope_id": kg.driver["id"]})
    ).json()
    by_id = {n["id"]: (n["name"], n["type"]) for n in graph["nodes"]}
    edges = {(by_id[e["source"]][0], e["type"], by_id[e["target"]][0]) for e in graph["edges"]}
    assert ("pkg/a.py", "defines", "Radio") in edges
    assert ("Radio", "contains", "Radio.set_channel") in edges
    assert ("Radio.set_channel", "calls", "helper") in edges
    assert ("pkg/a.py", "imports", "pkg/b.py") in edges
    assert ("pkg/b.py", "file") in by_id.values() and ("Radio", "class") in by_id.values()


async def test_project_graph_rebuild(client, admin_headers, session, kg, jobs):
    r = await client.post(f"/api/ingestion/projects/{kg.wifi['id']}/graph", headers=admin_headers)
    assert r.status_code == 200 and r.json() == {"queued": 2}
    assert [j[0] for j in jobs] == ["graph", "graph"]
    await run_jobs(session, jobs)
    assert set(await get_entities(client, admin_headers, kg.wifi["id"])) == {
        "Radio driver",
        "WPA3",
        "Access point",
    }


def test_expansion_prefers_the_bridge_between_relevant_entities() -> None:
    """Parallel chains project -> lead -> system: the bridge of the asked chain must win.

    Retrieved (in rank order): the project passage (project P0 and lead L0), then the system passages of
    every chain (S0..S2). The bridge passages "Lk operates Sk" are candidates; B0 links two seeds of the top
    passages, B1/B2 hang off lower-ranked systems and pull in their leads' other passages.
    """
    import uuid

    from opennotebook.graph.query import score_expansion

    ids = {name: uuid.uuid5(uuid.NAMESPACE_DNS, name) for name in ("P0 L0 S0 S1 S2 L1 L2".split())}
    chunks = {name: uuid.uuid5(uuid.NAMESPACE_URL, name) for name in ("A0 B0 B1 B2 A1 A2".split())}
    # rank 0: A0 (P0, L0); rank 1..3: system passages of chains 0..2
    seed_weight = {ids["P0"]: 1.0, ids["L0"]: 1.0, ids["S0"]: 1 / 2, ids["S1"]: 1 / 3, ids["S2"]: 1 / 4}
    relations = [
        (ids["L0"], ids["P0"], chunks["A0"]),  # already retrieved
        (ids["L0"], ids["S0"], chunks["B0"]),  # the bridge of the asked chain
        (ids["L1"], ids["S1"], chunks["B1"]),
        (ids["L2"], ids["S2"], chunks["B2"]),
    ]
    neighbour_chunks = {ids["L1"]: [chunks["B1"], chunks["A1"]], ids["L2"]: [chunks["B2"], chunks["A2"]]}
    score = score_expansion(seed_weight, relations, neighbour_chunks)
    ranked = sorted(score, key=lambda c: -score[c])
    assert ranked[1] == chunks["B0"]  # first after the already retrieved A0, which the caller drops
    assert score[chunks["B0"]] > score[chunks["B1"]] > score[chunks["B2"]]
    # an unweighted count (old behaviour) would rank B1 and B2 (evidence + neighbour mention) above B0
