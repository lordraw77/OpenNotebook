"""M1 integration: upload -> ingestion -> chunks -> hybrid search.

Covers ACL, switches, moves, notes and provider failures.

Embeddings come from a deterministic bag-of-words fake behind the real gateway; Qdrant runs in-process.
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from types import SimpleNamespace

import litellm
import pytest

from opennotebook.ingestion import queue
from opennotebook.ingestion.pipeline import (
    RetryableError,
    ingest_source,
    mark_failed_after_retries,
    purge_source,
    refresh_ancestors,
)
from opennotebook.ingestion.vectors import get_vector_index
from opennotebook.models import ModelPhase, Source, SourceStatus
from opennotebook.providers import service
from opennotebook.providers.catalog import DiscoveredModel
from opennotebook.storage import get_blob_store
from tests.conftest import login, make_user
from tests.factories import make_pdf

DIM = 64


def fake_vector(text: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0  # noqa: S324 - test hashing only
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.fixture
def embed_calls(monkeypatch):
    calls: list[dict] = []

    async def fake_aembedding(model, input, **kwargs):  # noqa: A002
        calls.append(
            {"model": model, "n": len(input), **{k: kwargs.get(k) for k in ("input_type", "api_key")}}
        )
        return SimpleNamespace(data=[{"embedding": fake_vector(t)} for t in input])

    monkeypatch.setattr(litellm, "aembedding", fake_aembedding)

    async def fake_list_models(kind, **_):
        return [
            DiscoveredModel("mistral-embed", capabilities={ModelPhase.embedding}, source="provider"),
            DiscoveredModel("other-embed", capabilities={ModelPhase.embedding}, source="provider"),
        ]

    monkeypatch.setattr(service, "list_models", fake_list_models)
    return calls


@pytest.fixture
def jobs(monkeypatch):
    recorded: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        queue, "enqueue_ingestion", lambda sid, reason="upload": recorded.append(("ingest", str(sid), reason))
    )
    monkeypatch.setattr(queue, "enqueue_purge", lambda sid: recorded.append(("purge", str(sid), "")))
    monkeypatch.setattr(
        queue, "enqueue_refresh_ancestors", lambda nid: recorded.append(("refresh", str(nid), ""))
    )
    monkeypatch.setattr(queue, "enqueue_summary", lambda sid: recorded.append(("summary", str(sid), "")))
    monkeypatch.setattr(queue, "enqueue_graph", lambda sid: recorded.append(("graph", str(sid), "")))
    return recorded


async def run_jobs(session, jobs) -> list:
    """Process recorded background jobs inline, like the worker would."""
    results = []
    store, index = get_blob_store(), get_vector_index()
    while jobs:
        kind, ident, reason = jobs.pop(0)
        if kind == "ingest":
            results.append(
                await ingest_source(session, uuid.UUID(ident), store=store, index=index, reason=reason)
            )
        elif kind == "purge":
            await purge_source(session, uuid.UUID(ident), store=store, index=index)
        elif kind == "graph":
            from opennotebook.graph.extract import extract_source_graph

            await extract_source_graph(session, uuid.UUID(ident), store)
        elif kind == "summary":
            from opennotebook.ingestion.summary import summarize_source

            await summarize_source(session, uuid.UUID(ident))
        else:
            await refresh_ancestors(session, uuid.UUID(ident), index=index)
        session.expire_all()
    return results


async def setup_embedding(client, headers) -> dict[str, str]:
    p = (
        await client.post(
            "/api/providers",
            headers=headers,
            json={"kind": "mistral", "name": "mistral", "api_key": "k" * 20},
        )
    ).json()
    await client.post(f"/api/providers/{p['id']}/sync", headers=headers)
    models = {
        m["model"]: m["id"]
        for m in (await client.get(f"/api/providers/{p['id']}/models", headers=headers)).json()
    }
    for mid in models.values():
        await client.patch(f"/api/provider-models/{mid}", headers=headers, json={"enabled": True})
    r = await client.put(
        "/api/model-assignments/embedding", headers=headers, json={"model_ids": [models["mistral-embed"]]}
    )
    assert r.status_code == 200, r.text
    return models


async def node(client, headers, kind, name, parent=None) -> dict:
    r = await client.post(
        "/api/nodes", headers=headers, json={"kind": kind, "name": name, "parent_id": parent}
    )
    assert r.status_code == 201, r.text
    return r.json()


async def upload(client, headers, notebook_id, files) -> list[dict]:
    r = await client.post(
        f"/api/nodes/{notebook_id}/sources",
        headers=headers,
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
    )
    assert r.status_code == 201, r.text
    return r.json()


async def search(client, headers, scope_id, query) -> list[dict]:
    r = await client.post("/api/search", headers=headers, json={"scope_id": scope_id, "query": query})
    assert r.status_code == 200, r.text
    return r.json()["hits"]


RADIO_MD = (
    b"# Radio\n\nThe radio driver selects the channel and sets the transmit power before sending frames.\n"
)
MANUAL_PDF = make_pdf(
    [[(20, "User Manual"), (11, "Press the reset button for ten seconds to restore factory settings.")]]
)


@pytest.fixture
async def world(client, admin_headers, session, embed_calls, jobs):
    """wifi/source/driver (radio.md) and wifi/docs/manuals (manual.pdf), both indexed."""
    await setup_embedding(client, admin_headers)
    wifi = await node(client, admin_headers, "project", "wifi")
    src = await node(client, admin_headers, "workspace", "source", wifi["id"])
    docs = await node(client, admin_headers, "workspace", "docs", wifi["id"])
    driver = await node(client, admin_headers, "notebook", "driver", src["id"])
    manuals = await node(client, admin_headers, "notebook", "manuals", docs["id"])
    up1 = await upload(client, admin_headers, driver["id"], [("radio.md", RADIO_MD)])
    up2 = await upload(client, admin_headers, manuals["id"], [("manual.pdf", MANUAL_PDF)])
    assert await run_jobs(session, jobs) == [SourceStatus.ready, SourceStatus.ready]
    return SimpleNamespace(
        wifi=wifi,
        src=src,
        docs=docs,
        driver=driver,
        manuals=manuals,
        radio=up1[0]["source"],
        manual=up2[0]["source"],
    )


async def test_upload_ingest_chunks_and_file(client, admin_headers, session, world, embed_calls, jobs):
    radio = (await client.get(f"/api/sources/{world.radio['id']}", headers=admin_headers)).json()
    assert radio["status"] == "ready" and radio["chunk_count"] >= 1 and radio["embedding_model_id"]
    chunks = (await client.get(f"/api/sources/{world.radio['id']}/chunks", headers=admin_headers)).json()
    assert chunks[0]["heading_path"] == ["Radio"] and "transmit power" in chunks[0]["text"]
    manual_chunks = (
        await client.get(f"/api/sources/{world.manual['id']}/chunks", headers=admin_headers)
    ).json()
    assert manual_chunks[0]["page_start"] == 1
    file = await client.get(f"/api/sources/{world.manual['id']}/file", headers=admin_headers)
    assert file.content == MANUAL_PDF and file.headers["content-type"] == "application/pdf"
    assert all(c["input_type"] is None for c in embed_calls)  # Mistral needs no input_type

    # duplicates, unsupported types and wrong targets
    again = await upload(
        client,
        admin_headers,
        world.driver["id"],
        [("copy.md", RADIO_MD), ("pack.7z", b"7z\xbc\xaf\x27\x1c" + bytes(26))],
    )
    assert again[0]["duplicate"] is True and again[1]["error"].startswith("7z archives")
    assert jobs == []
    r = await client.post(
        f"/api/nodes/{world.src['id']}/sources",
        headers=admin_headers,
        files=[("files", ("a.md", b"x", "text/plain"))],
    )
    assert r.status_code == 422


async def test_scoped_hybrid_search(client, admin_headers, world):
    hits = await search(client, admin_headers, world.wifi["id"], "reset button factory settings")
    assert hits and hits[0]["source_title"] == "manual.pdf" and hits[0]["chunk"]["page_start"] == 1
    assert {h["source_title"] for h in await search(client, admin_headers, world.wifi["id"], "channel")} >= {
        "radio.md"
    }
    only_src = await search(client, admin_headers, world.src["id"], "reset button factory settings")
    assert all(h["source_title"] == "radio.md" for h in only_src)
    assert await search(client, admin_headers, world.manuals["id"], "radio driver channel") == [] or all(
        h["source_title"] == "manual.pdf"
        for h in await search(client, admin_headers, world.manuals["id"], "radio")
    )


async def test_switches_exclude_from_search(client, admin_headers, world):
    await client.patch(f"/api/sources/{world.manual['id']}", headers=admin_headers, json={"active": False})
    titles = {
        h["source_title"] for h in await search(client, admin_headers, world.wifi["id"], "reset button")
    }
    assert "manual.pdf" not in titles
    await client.patch(f"/api/sources/{world.manual['id']}", headers=admin_headers, json={"active": True})
    await client.patch(f"/api/nodes/{world.src['id']}", headers=admin_headers, json={"active": False})
    titles = {
        h["source_title"]
        for h in await search(client, admin_headers, world.wifi["id"], "radio channel power")
    }
    assert "radio.md" not in titles and "manual.pdf" in titles


async def test_acl_prefilter(client, admin_headers, session, world):
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    await client.put(
        f"/api/nodes/{world.docs['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    # Bob searches the whole project but can only read docs: radio.md must never appear.
    for query in ("radio driver channel transmit power", "reset button"):
        titles = {h["source_title"] for h in await search(client, bob_headers, world.wifi["id"], query)}
        assert "radio.md" not in titles
    assert (
        await client.post(
            "/api/search", headers=bob_headers, json={"scope_id": world.src["id"], "query": "radio"}
        )
    ).status_code == 404
    assert (await client.get(f"/api/sources/{world.radio['id']}", headers=bob_headers)).status_code == 404
    listed = {s["title"] for s in (await client.get("/api/sources", headers=bob_headers)).json()}
    assert listed == {"manual.pdf"}
    r = await client.post(
        f"/api/nodes/{world.manuals['id']}/sources",
        headers=bob_headers,
        files=[("files", ("a.md", b"# A", "text/plain"))],
    )
    assert r.status_code == 403


async def test_delete_purges_vectors_and_move_refreshes_ancestors(
    client, admin_headers, session, world, jobs
):
    # move driver notebook under docs: searches on docs now find radio.md, on source they do not
    r = await client.patch(
        f"/api/nodes/{world.driver['id']}", headers=admin_headers, json={"parent_id": world.docs["id"]}
    )
    assert r.status_code == 200 and jobs[0][0] == "refresh"
    await run_jobs(session, jobs)
    assert {
        h["source_title"] for h in await search(client, admin_headers, world.docs["id"], "radio channel")
    } >= {"radio.md"}
    assert await search(client, admin_headers, world.src["id"], "radio channel") == []

    assert (
        await client.delete(f"/api/sources/{world.radio['id']}", headers=admin_headers)
    ).status_code == 204
    await run_jobs(session, jobs)
    assert "radio.md" not in {
        h["source_title"] for h in await search(client, admin_headers, world.wifi["id"], "radio")
    }
    assert (await client.get(f"/api/sources/{world.radio['id']}", headers=admin_headers)).status_code == 404
    assert not await get_blob_store().exists(f"sources/{world.radio['id']}/original")


async def test_indexed_notes(client, admin_headers, session, world, jobs):
    r = await client.post(
        f"/api/nodes/{world.manuals['id']}/notes",
        headers=admin_headers,
        json={
            "title": "Antenna tip",
            "body_md": "Point the antenna towards the window for better signal.",
            "indexed": True,
        },
    )
    assert r.status_code == 201
    note = r.json()
    await run_jobs(session, jobs)
    hits = await search(client, admin_headers, world.manuals["id"], "antenna window signal")
    assert hits and hits[0]["source_title"] == "Antenna tip"

    await client.patch(f"/api/notes/{note['id']}", headers=admin_headers, json={"indexed": False})
    await run_jobs(session, jobs)
    assert "Antenna tip" not in {
        h["source_title"] for h in await search(client, admin_headers, world.manuals["id"], "antenna")
    }
    again = (
        await client.patch(f"/api/notes/{note['id']}", headers=admin_headers, json={"indexed": True})
    ).json()
    assert again["source_id"] and again["source_id"] != note["source_id"]
    await run_jobs(session, jobs)
    notes = (await client.get(f"/api/nodes/{world.manuals['id']}/notes", headers=admin_headers)).json()
    assert notes[0]["source_status"] == "ready"
    assert (await client.delete(f"/api/notes/{note['id']}", headers=admin_headers)).status_code == 204


async def test_provider_failure_is_retryable(client, admin_headers, session, world, monkeypatch):
    async def failing(model, input, **kwargs):  # noqa: A002
        raise litellm.RateLimitError("429", llm_provider="mistral", model=model)

    monkeypatch.setattr(litellm, "aembedding", failing)
    sid = uuid.UUID(world.radio["id"])
    with pytest.raises(RetryableError):
        await ingest_source(
            session, sid, store=get_blob_store(), index=get_vector_index(), reason="retry", attempt=2
        )
    session.expire_all()
    source = await session.get(Source, sid)
    assert source.status == SourceStatus.embedding and source.error["code"] == "provider_error"
    await mark_failed_after_retries(session, sid, "gave up")
    session.expire_all()
    assert (await session.get(Source, sid)).status == SourceStatus.failed


async def test_status_page_and_project_reindex(client, admin_headers, world, jobs, session):
    status = (await client.get("/api/ingestion/status", headers=admin_headers)).json()
    assert status["by_status"]["ready"] == 2
    project = next(p for p in status["projects"] if p["project_name"] == "wifi")
    assert project["embedding_model"] == "mistral/mistral-embed" and project["stale_sources"] == 0

    # project override with another embedding model -> sources become stale until re-indexed
    models = {
        m["model"]: m["id"]
        for m in (
            await client.get(
                "/api/models/selectable",
                params={"phase": "embedding", "include_all": True},
                headers=admin_headers,
            )
        ).json()
    }
    await client.put(
        "/api/model-assignments/embedding",
        headers=admin_headers,
        json={"project_id": world.wifi["id"], "model_ids": [models["other-embed"]]},
    )
    project = next(
        p for p in (await client.get("/api/ingestion/status", headers=admin_headers)).json()["projects"]
    )
    assert project["embedding_source"] == "project" and project["stale_sources"] == 2
    r = await client.post(f"/api/ingestion/projects/{world.wifi['id']}/reindex", headers=admin_headers)
    assert r.json() == {"queued": 2}
    await run_jobs(session, jobs)
    project = next(
        p for p in (await client.get("/api/ingestion/status", headers=admin_headers)).json()["projects"]
    )
    assert project["stale_sources"] == 0
    assert await search(client, admin_headers, world.wifi["id"], "reset button")


async def test_missing_embedding_model_is_reported(client, admin_headers, session, embed_calls, jobs):
    p = await node(client, admin_headers, "project", "empty")
    nb = await node(client, admin_headers, "notebook", "nb", p["id"])
    up = await upload(client, admin_headers, nb["id"], [("a.txt", b"hello world")])
    with pytest.raises(RetryableError, match="No model configured"):
        await run_jobs(session, jobs)
    assert (await client.get(f"/api/sources/{up[0]['source']['id']}", headers=admin_headers)).json()["error"][
        "code"
    ] == "provider_error"
    r = await client.post("/api/search", headers=admin_headers, json={"scope_id": p["id"], "query": "hello"})
    assert r.status_code == 503


async def test_search_caps_slow_provider_timeout(client, admin_headers, world, monkeypatch):
    seen = {}

    async def slow(model, input, **kwargs):  # noqa: A002
        seen["timeout"] = kwargs["timeout"]
        raise litellm.Timeout("slow", model=model, llm_provider="ollama")

    monkeypatch.setattr(litellm, "aembedding", slow)
    r = await client.post(
        "/api/search", headers=admin_headers, json={"scope_id": world.wifi["id"], "query": "x"}
    )
    assert r.status_code == 503 and "Timeout" in r.json()["detail"]
    assert seen["timeout"] == 30  # provider timeout is 60, capped by SEARCH_TIMEOUT_S
