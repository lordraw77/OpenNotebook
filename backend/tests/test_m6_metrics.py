# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""M6 observability: application metrics are recorded with bounded labels."""

from __future__ import annotations

from prometheus_client import REGISTRY

from tests.test_chat import chat, new_conversation  # noqa: F401 - fixtures
from tests.test_m5_admin import ask
from tests.test_sources import embed_calls, jobs, world  # noqa: F401 - fixtures


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


async def test_metrics_for_ingestion_provider_calls_and_chat(client, admin_headers, world, chat):
    # world fixture ingested radio.md (markdown → file) and manual.pdf
    assert sample("opennotebook_ingestion_jobs_total", kind="file", status="ready") >= 2
    assert (
        sample("opennotebook_provider_calls_total", provider="mistral", phase="embedding", outcome="ok") >= 2
    )

    before_err = sample("opennotebook_provider_calls_total", provider="groq", phase="chat", outcome="error")
    before_ttft = sample("opennotebook_chat_time_to_first_token_seconds_count", mode="chat")
    before_ok = sample("opennotebook_chat_answers_total", mode="chat", status="complete")
    chat.fake.behavior["chat-a"] = "fail"  # fallback to chat-b: one error, one ok
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    await ask(client, admin_headers, conv["id"], "How do I restore the factory settings?")
    assert (
        sample("opennotebook_provider_calls_total", provider="groq", phase="chat", outcome="error")
        == before_err + 1
    )
    assert sample("opennotebook_chat_time_to_first_token_seconds_count", mode="chat") == before_ttft + 1
    assert sample("opennotebook_chat_answers_total", mode="chat", status="complete") == before_ok + 1
    assert sample("opennotebook_retrieval_duration_seconds_count") >= 1

    # labels never carry ids or user input: every provider label is a provider name
    providers = {
        s.labels["provider"]
        for m in REGISTRY.collect()
        if m.name == "opennotebook_provider_calls"
        for s in m.samples
    }
    assert providers <= {"mistral", "groq"}

    body = (await client.get("/metrics")).text
    assert "opennotebook_chat_time_to_first_token_seconds_bucket" in body


async def test_rate_limits_and_key_rotation(client, admin_headers, session, world, chat, monkeypatch):
    """Per-user limits on chat/research/search (T14) and master-key rotation of stored provider keys."""
    import base64
    import os as _os

    from sqlalchemy import select

    from opennotebook.cli import rotate_encryption_key
    from opennotebook.config import get_settings
    from opennotebook.crypto import get_secret_box
    from opennotebook.models import Secret

    settings = get_settings()
    monkeypatch.setattr(settings, "chat_rate_limit_per_minute", 2)
    monkeypatch.setattr(settings, "search_rate_limit_per_minute", 1)
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    for _ in range(2):
        r = await client.post(
            f"/api/conversations/{conv['id']}/messages", headers=admin_headers, json={"content": "hi"}
        )
        assert r.status_code == 200
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages", headers=admin_headers, json={"content": "hi"}
    )
    assert r.status_code == 429
    body = {"scope_id": world.wifi["id"], "query": "reset"}
    assert (await client.post("/api/search", headers=admin_headers, json=body)).status_code == 200
    assert (await client.post("/api/search", headers=admin_headers, json=body)).status_code == 429

    # rotation: provider keys encrypted with the old key stay readable, then are re-encrypted with the new one
    secrets = list((await session.scalars(select(Secret))).all())
    assert secrets  # mistral + groq keys from the fixtures
    before = {s.id: get_secret_box().decrypt(s.ciphertext, s.nonce) for s in secrets}
    old_key = settings.app_encryption_key
    new_key = base64.b64encode(_os.urandom(32)).decode()
    monkeypatch.setattr(settings, "app_encryption_key", new_key)
    monkeypatch.setattr(settings, "app_encryption_key_previous", old_key)
    assert {
        s.id: get_secret_box().decrypt(s.ciphertext, s.nonce) for s in secrets
    } == before  # fallback works
    report = await rotate_encryption_key()
    assert report["re_encrypted"] == len(secrets) and report["already_current"] == 0
    monkeypatch.setattr(settings, "app_encryption_key_previous", "")
    session.expire_all()
    rotated = list((await session.scalars(select(Secret))).all())
    assert {s.id: get_secret_box().decrypt(s.ciphertext, s.nonce) for s in rotated} == before  # new key only
    assert all(s.key_version == 2 for s in rotated)
    # a wrong previous key: nothing changes
    monkeypatch.setattr(settings, "app_encryption_key", base64.b64encode(_os.urandom(32)).decode())
    monkeypatch.setattr(settings, "app_encryption_key_previous", base64.b64encode(_os.urandom(32)).decode())
    import pytest

    with pytest.raises(SystemExit, match="nothing was changed"):
        await rotate_encryption_key()


async def test_reconcile_finds_and_repairs_inconsistencies(client, admin_headers, session, world, jobs):
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from opennotebook.ingestion.pipeline import blob_key
    from opennotebook.ingestion.reconcile import reconcile
    from opennotebook.ingestion.vectors import PointData, get_vector_index
    from opennotebook.models import Source, SourceStatus
    from opennotebook.storage import get_blob_store
    from tests.test_sources import run_jobs

    index, store = get_vector_index(), get_blob_store()
    report = await reconcile(session, index, store)
    assert report["ok"] is True and report["sources_checked"] == 2

    radio = await session.get(Source, _uuid.UUID(world.radio["id"]))
    manual = await session.get(Source, _uuid.UUID(world.manual["id"]))
    collection = radio.vector_collection
    await index.delete_source(collection, radio.id)  # vectors lost
    await store.delete(blob_key(manual.id, "original"))  # file lost
    ghost = _uuid.uuid4()
    await index.upsert(
        collection,
        [
            PointData(
                chunk_id=_uuid.uuid4(),
                dense=[0.1] * 64,
                sparse=([1], [1.0]),
                payload={"source_id": str(ghost)},
            )
        ],
    )
    stuck = Source(
        notebook_id=manual.notebook_id, kind=radio.kind, title="stuck.md", content_sha256=b"x" * 32,
        status=SourceStatus.parsing, warnings=[], metadata_={},
    )  # fmt: skip
    session.add(stuck)
    await session.commit()
    await session.execute(
        update(Source).where(Source.id == stuck.id).values(updated_at=datetime.now(UTC) - timedelta(hours=3))
    )
    await session.commit()

    report = await reconcile(session, index, store)
    assert report["ok"] is False
    assert [m["title"] for m in report["vector_mismatch"]] == ["radio.md"]
    assert report["vector_mismatch"][0]["vectors"] == 0
    assert [m["title"] for m in report["missing_file"]] == ["manual.pdf"]
    assert [m["title"] for m in report["stuck"]] == ["stuck.md"]
    assert report["orphan_vectors"] == {collection: [str(ghost)]}

    report = await reconcile(session, index, store, fix=True)
    assert report["fixed"] == {"requeued": 2, "orphan_sources_removed": 1}
    assert {j[1] for j in jobs if j[0] == "ingest"} == {str(radio.id), str(stuck.id)}
    jobs[:] = [j for j in jobs if j[1] == str(radio.id)]
    await run_jobs(session, jobs)
    session.expire_all()
    after = await reconcile(session, index, store)
    assert after["vector_mismatch"] == [] and after["orphan_vectors"] == {}
