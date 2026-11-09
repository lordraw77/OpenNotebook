"""Unit tests that need no services beyond the shared fixtures."""

from __future__ import annotations

import json

import httpx
import pytest

from opennotebook.crypto import SecretBox, get_secret_box, secret_hint
from opennotebook.logging_setup import redact
from opennotebook.models import ModelPhase, ProviderKind
from opennotebook.providers.catalog import infer_capabilities, list_models, supports_phase
from opennotebook.storage import FilesystemBlobStore, _safe_key


def test_secret_box_roundtrip_and_tamper():
    box = get_secret_box()
    ct, nonce = box.encrypt("gsk_supersecretvalue")
    assert b"supersecret" not in ct
    assert box.decrypt(ct, nonce) == "gsk_supersecretvalue"
    with pytest.raises(Exception):  # noqa: B017
        box.decrypt(ct[:-1] + bytes([ct[-1] ^ 1]), nonce)
    with pytest.raises(ValueError):
        SecretBox("bm90LTMyLWJ5dGVz")
    assert secret_hint("abcdefgh1234") == "…1234"


@pytest.mark.parametrize(
    "text",
    [
        "key gsk_abcdefghijklmnopqrstuvwx leaked",
        "Authorization: Bearer abcdefghijklmnop123",
        "https://x/models?key=AIzaSyA1234567890abcdefghijk",
        "token nvapi-abcdefghijklmnopqrstuv",
        "hf_abcdefghijklmnopqrstu",
    ],
)
def test_redaction(text):
    out = redact(text)
    assert "[REDACTED]" in out
    assert "abcdefghijklmnop" not in out and "1234567890abc" not in out


@pytest.mark.parametrize(
    ("model", "expected"),
    [
        ("llama-3.3-70b-versatile", {ModelPhase.chat}),
        ("meta-llama/llama-4-scout-17b-16e-instruct", {ModelPhase.chat, ModelPhase.vision}),
        ("whisper-large-v3", set()),
        ("nvidia/nv-embedqa-e5-v5", {ModelPhase.embedding}),
        ("nvidia/llama-3.2-nv-rerankqa-1b-v2", {ModelPhase.rerank}),
        ("@cf/baai/bge-m3", {ModelPhase.embedding}),
        ("mistral-ocr-latest", {ModelPhase.ocr}),
        ("meta-llama/llama-guard-4-12b", set()),
    ],
)
def test_infer_capabilities(model, expected):
    assert infer_capabilities(model) == expected


def test_phase_requirements():
    assert supports_phase([ModelPhase.vision], ModelPhase.ocr)
    assert supports_phase([ModelPhase.chat], ModelPhase.graph_extraction)
    assert not supports_phase([ModelPhase.chat], ModelPhase.embedding)


def _mock(routes: dict[str, dict]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, body in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, json=body)
        return httpx.Response(404)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_list_models_gemini_uses_header_and_metadata():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["key_header"] = request.headers.get("x-goog-api-key")
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        models = await list_models(
            ProviderKind.gemini, api_key="AQ.secret", base_url=None, options={}, client=c
        )
    assert seen["key_header"] == "AQ.secret" and "secret" not in seen["url"]
    caps = {m.model: m.capabilities for m in models}
    assert caps["gemini-2.5-flash"] == {ModelPhase.chat, ModelPhase.vision}
    assert caps["gemini-embedding-001"] == {ModelPhase.embedding}


async def test_list_models_mistral_and_cloudflare():
    async with _mock(
        {
            "https://api.mistral.ai/v1/models": {
                "data": [
                    {"id": "mistral-small-latest", "capabilities": {"completion_chat": True, "vision": True}},
                    {"id": "mistral-embed", "capabilities": {"completion_chat": False}},
                    {"id": "mistral-ocr-latest", "capabilities": {"ocr": True}},
                ]
            }
        }
    ) as c:
        models = await list_models(ProviderKind.mistral, api_key="k", base_url=None, options={}, client=c)
    caps = {m.model: m.capabilities for m in models}
    assert caps == {
        "mistral-small-latest": {ModelPhase.chat, ModelPhase.vision},
        "mistral-embed": {ModelPhase.embedding},
        "mistral-ocr-latest": {ModelPhase.ocr},
    }

    async with _mock(
        {
            "https://api.cloudflare.com/client/v4/accounts/acc/ai/models/search": {
                "result": [
                    {"name": "@cf/meta/llama-3.1-8b-instruct", "task": {"name": "Text Generation"}},
                    {"name": "@cf/baai/bge-m3", "task": {"name": "Text Embeddings"}},
                    {"name": "@cf/baai/bge-reranker-base", "task": {"name": "Text Classification"}},
                ],
                "result_info": {"per_page": 100, "total_count": 3},
            }
        }
    ) as c:
        models = await list_models(
            ProviderKind.cloudflare, api_key="k", base_url=None, options={"account_id": "acc"}, client=c
        )
    caps = {m.model: m.capabilities for m in models}
    assert caps["@cf/baai/bge-reranker-base"] == {ModelPhase.rerank}
    assert caps["@cf/baai/bge-m3"] == {ModelPhase.embedding}


async def test_list_models_ollama_capabilities():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}, {"name": "nomic-embed-text"}]})
        name = json.loads(request.content)["model"]
        caps = ["completion", "tools"] if name == "qwen3:8b" else ["embedding"]
        return httpx.Response(200, json={"capabilities": caps, "model_info": {"qwen3.context_length": 40960}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        models = await list_models(
            ProviderKind.ollama, api_key=None, base_url="http://ollama.lan:11434/", options={}, client=c
        )
    caps = {m.model: m.capabilities for m in models}
    assert caps == {"qwen3:8b": {ModelPhase.chat}, "nomic-embed-text": {ModelPhase.embedding}}


async def test_filesystem_blob_store(tmp_path):
    store = FilesystemBlobStore(str(tmp_path))
    await store.ensure_ready()
    await store.put("sources/abc/original", b"data")
    assert await store.get("sources/abc/original") == b"data"
    assert await store.exists("sources/abc/original")
    await store.delete("sources/abc/original")
    assert not await store.exists("sources/abc/original")
    for bad in ("../etc/passwd", "/abs", "a//b", "a/./b"):
        with pytest.raises(ValueError):
            _safe_key(bad)


async def test_ollama_rerank_calls_the_proxy_rerank_endpoint(monkeypatch):
    """Ollama has no rerank API: the gateway posts Jina/Cohere-style requests to <base_url>/rerank."""
    from types import SimpleNamespace

    import httpx

    from opennotebook.providers.gateway import _ollama_rerank

    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = __import__("json").loads(request.content)
        return httpx.Response(
            200,
            json={"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]},
        )

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    resolved = SimpleNamespace(
        provider=SimpleNamespace(base_url="http://proxy:11434/"),
        model=SimpleNamespace(model="reranker"),
        api_key=None,
    )
    out = await _ollama_rerank(resolved, "q", ["a", "b"], 2, 5)
    assert out == [(1, 0.9), (0, 0.1)]
    assert seen["url"] == "http://proxy:11434/rerank" and seen["auth"] is None
    assert seen["body"] == {"model": "reranker", "query": "q", "documents": ["a", "b"], "top_n": 2}
