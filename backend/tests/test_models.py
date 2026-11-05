"""Provider registry, model selection per phase / per project, and gateway fallback."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opennotebook.models import ModelPhase
from opennotebook.providers import service
from opennotebook.providers.catalog import DiscoveredModel
from tests.conftest import login, make_user

CATALOG = {
    "groq": [
        DiscoveredModel("llama-fast", capabilities={ModelPhase.chat}),
        DiscoveredModel("whisper-large-v3", capabilities=set()),
    ],
    "mistral": [
        DiscoveredModel(
            "mistral-small", capabilities={ModelPhase.chat, ModelPhase.vision}, source="provider"
        ),
        DiscoveredModel("mistral-embed", capabilities={ModelPhase.embedding}, source="provider"),
    ],
    "gemini": [
        DiscoveredModel("gemini-flash", capabilities={ModelPhase.chat, ModelPhase.vision}, source="provider"),
        DiscoveredModel("gemini-embedding", capabilities={ModelPhase.embedding}, source="provider"),
    ],
}


@pytest.fixture(autouse=True)
def fake_catalog(monkeypatch):
    async def fake_list_models(kind, **_):
        return CATALOG[kind.value]

    monkeypatch.setattr(service, "list_models", fake_list_models)


async def add_provider(client, headers, kind, key="secret-key-123456"):
    resp = await client.post(
        "/api/providers", headers=headers, json={"kind": kind, "name": kind, "api_key": key}
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    assert (await client.post(f"/api/providers/{pid}/sync", headers=headers)).status_code == 200
    models = (await client.get(f"/api/providers/{pid}/models", headers=headers)).json()
    return resp.json(), {m["model"]: m for m in models}


async def enable(client, headers, *models):
    for m in models:
        resp = await client.patch(f"/api/provider-models/{m['id']}", headers=headers, json={"enabled": True})
        assert resp.status_code == 200, resp.text


async def test_provider_key_is_encrypted_and_never_returned(client, admin_headers, session):
    from opennotebook.models import Secret

    provider, _ = await add_provider(client, admin_headers, "groq", key="gsk_live_key_ABCD")
    assert provider["api_key_hint"] == "…ABCD"
    listing = await client.get("/api/providers", headers=admin_headers)
    assert "gsk_live_key" not in listing.text
    secret = (await session.execute(Secret.__table__.select())).first()
    assert b"gsk_live_key" not in secret.ciphertext

    missing_key = await client.post(
        "/api/providers", headers=admin_headers, json={"kind": "mistral", "name": "m2"}
    )
    assert missing_key.status_code == 422
    cf = await client.post(
        "/api/providers",
        headers=admin_headers,
        json={"kind": "cloudflare", "name": "cf", "api_key": "k" * 10},
    )
    assert cf.status_code == 422  # account_id option required


async def test_provider_admin_only(client, alice_headers):
    assert (await client.get("/api/providers", headers=alice_headers)).status_code == 403


async def test_sync_preserves_manual_capabilities(client, admin_headers, session):
    provider, models = await add_provider(client, admin_headers, "groq")
    whisper = models["whisper-large-v3"]
    assert whisper["capabilities"] == []
    await client.patch(
        f"/api/provider-models/{whisper['id']}", headers=admin_headers, json={"capabilities": ["chat"]}
    )
    await client.post(f"/api/providers/{provider['id']}/sync", headers=admin_headers)
    again = (await client.get(f"/api/providers/{provider['id']}/models", headers=admin_headers)).json()
    assert next(m for m in again if m["model"] == "whisper-large-v3")["capabilities"] == ["chat"]


async def test_global_chain_validation(client, admin_headers):
    _, groq = await add_provider(client, admin_headers, "groq")
    _, mistral = await add_provider(client, admin_headers, "mistral")

    # disabled model cannot be assigned
    resp = await client.put(
        "/api/model-assignments/chat", headers=admin_headers, json={"model_ids": [groq["llama-fast"]["id"]]}
    )
    assert resp.status_code == 422
    await enable(
        client, admin_headers, groq["llama-fast"], mistral["mistral-small"], mistral["mistral-embed"]
    )

    chain = await client.put(
        "/api/model-assignments/chat",
        headers=admin_headers,
        json={"model_ids": [groq["llama-fast"]["id"], mistral["mistral-small"]["id"]]},
    )
    assert chain.status_code == 200, chain.text
    assert [c["model"]["model"] for c in chain.json()["effective"]] == ["llama-fast", "mistral-small"]

    wrong_cap = await client.put(
        "/api/model-assignments/embedding",
        headers=admin_headers,
        json={"model_ids": [groq["llama-fast"]["id"]]},
    )
    assert wrong_cap.status_code == 422
    two_embed = await client.put(
        "/api/model-assignments/embedding",
        headers=admin_headers,
        json={"model_ids": [mistral["mistral-embed"]["id"], mistral["mistral-embed"]["id"]]},
    )
    assert two_embed.status_code == 422
    vision_for_ocr = await client.put(
        "/api/model-assignments/ocr",
        headers=admin_headers,
        json={"model_ids": [mistral["mistral-small"]["id"]]},
    )
    assert vision_for_ocr.status_code == 200  # a vision model may serve OCR


async def test_per_project_embedding_override(client, session, admin_headers):
    _, mistral = await add_provider(client, admin_headers, "mistral")
    _, gemini = await add_provider(client, admin_headers, "gemini")
    await enable(client, admin_headers, mistral["mistral-embed"], gemini["gemini-embedding"])
    await client.put(
        "/api/model-assignments/embedding",
        headers=admin_headers,
        json={"model_ids": [mistral["mistral-embed"]["id"]]},
    )

    await make_user(session, "owner@example.com")
    owner = await login(client, "owner@example.com")
    project = (
        await client.post("/api/nodes", headers=owner, json={"kind": "project", "name": "wifi"})
    ).json()

    # owners may override their project but not the global default
    assert (
        await client.put(
            "/api/model-assignments/embedding",
            headers=owner,
            json={"model_ids": [gemini["gemini-embedding"]["id"]]},
        )
    ).status_code == 403
    resp = await client.put(
        "/api/model-assignments/embedding",
        headers=owner,
        json={"project_id": project["id"], "model_ids": [gemini["gemini-embedding"]["id"]]},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["source"] == "project"
    assert resp.json()["effective"][0]["model"]["model"] == "gemini-embedding"

    phases = {p["phase"]: p for p in (await client.get("/api/model-assignments", headers=owner)).json()}
    assert phases["embedding"]["effective"][0]["model"]["model"] == "mistral-embed"  # global unchanged

    # removing the override falls back to the global chain
    cleared = await client.put(
        "/api/model-assignments/embedding", headers=owner, json={"project_id": project["id"], "model_ids": []}
    )
    assert cleared.json()["source"] == "global"


async def test_selectable_models_for_chat_selector(client, admin_headers, alice_headers):
    _, groq = await add_provider(client, admin_headers, "groq")
    _, mistral = await add_provider(client, admin_headers, "mistral")
    await enable(
        client, admin_headers, groq["llama-fast"], mistral["mistral-small"], mistral["mistral-embed"]
    )
    await client.put(
        "/api/model-assignments/chat",
        headers=admin_headers,
        json={"model_ids": [mistral["mistral-small"]["id"]]},
    )
    resp = await client.get("/api/models/selectable", params={"phase": "chat"}, headers=alice_headers)
    names = [m["model"] for m in resp.json()]
    assert names == ["mistral-small", "llama-fast"]  # default chain first, embedding model excluded


async def test_gateway_fallback_and_user_selection(client, admin_headers, session, monkeypatch):
    import litellm

    from opennotebook.providers.gateway import GatewayError, ModelGateway

    _, groq = await add_provider(client, admin_headers, "groq")
    _, mistral = await add_provider(client, admin_headers, "mistral")
    await enable(
        client, admin_headers, groq["llama-fast"], mistral["mistral-small"], mistral["mistral-embed"]
    )
    await client.put(
        "/api/model-assignments/chat",
        headers=admin_headers,
        json={"model_ids": [groq["llama-fast"]["id"], mistral["mistral-small"]["id"]]},
    )
    calls = []

    async def fake_acompletion(model, messages, **kwargs):
        calls.append((model, kwargs.get("api_key")))
        if model.startswith("groq/"):
            raise litellm.RateLimitError("429", llm_provider="groq", model=model)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))])

    monkeypatch.setattr(litellm, "acompletion", fake_acompletion)
    gw = ModelGateway(session)
    result = await gw.complete(ModelPhase.chat, [{"role": "user", "content": "x"}])
    assert result.used.model.model == "mistral-small"
    assert [c[0] for c in calls] == ["groq/llama-fast", "mistral/mistral-small"]
    assert calls[0][1] == "secret-key-123456"  # decrypted key passed per call
    assert result.attempts[0]["error"] == "RateLimitError"

    # a user-selected model is tried first
    calls.clear()
    import uuid

    result = await gw.complete(
        ModelPhase.chat,
        [{"role": "user", "content": "x"}],
        selected_model_id=uuid.UUID(mistral["mistral-small"]["id"]),
    )
    assert calls[0][0] == "mistral/mistral-small"

    with pytest.raises(GatewayError):
        await gw.complete(
            ModelPhase.chat,
            [{"role": "user", "content": "x"}],
            selected_model_id=uuid.UUID(mistral["mistral-embed"]["id"]),
        )


async def test_bootstrap_from_env(session, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "a" * 20)
    monkeypatch.setenv("MISTRAL_API_KEY", "m" * 20)
    monkeypatch.setenv("CLOUDFLARE_API_KEY", "")
    monkeypatch.setenv("OLLAMA_API_BASE", "")
    for var in ("OPENROUTER_API_KEY", "GEMINI_API_KEY", "CEREBRAS_API_KEY", "NVIDIA_API_KEY", "HF_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("MODEL_CHAT", "groq/llama-fast,mistral/mistral-small")
    monkeypatch.setenv("MODEL_EMBEDDING", "mistral/mistral-embed")

    created = await service.import_providers_from_env(session)
    assert sorted(created) == ["groq", "mistral"]
    assert await service.import_providers_from_env(session) == []  # idempotent

    from sqlalchemy import select

    from opennotebook.models import Provider

    for p in (await session.scalars(select(Provider))).all():
        await service.sync_models(session, p)
    results = await service.import_assignments_from_env(session)
    assert results["chat"] == "configured" and results["embedding"] == "configured"
    assert (await service.import_assignments_from_env(session))["chat"] == "kept existing"
