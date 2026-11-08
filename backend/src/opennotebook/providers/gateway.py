"""Model gateway: per-phase model resolution, fallback chains and calls through LiteLLM.

Resolution order for a phase:
  1. an explicit model chosen by the user (e.g. the chat model selector), if it is allowed for the phase;
  2. the project's override chain for that phase, if the project defines one;
  3. the global default chain.
Embedding never falls back (vectors from different models are not comparable).
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.crypto import get_secret_box
from opennotebook.models import ModelPhase, PhaseAssignment, Provider, ProviderKind, ProviderModel, Secret
from opennotebook.providers.catalog import PROVIDERS, SINGLE_MODEL_PHASES, supports_phase

# LiteLLM must not fetch its model cost map from the internet at import time.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


class GatewayError(Exception):
    def __init__(self, message: str, attempts: list[dict] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []

    def describe(self) -> str:
        """Message plus the failed attempts, e.g. `... (ollama/bge-m3: Timeout)`."""
        failed = [f"{a['model']}: {a['error']}" for a in self.attempts if a.get("error")]
        return f"{self} ({'; '.join(failed)})" if failed else str(self)


@dataclass
class ResolvedModel:
    provider: Provider
    model: ProviderModel
    params: dict = field(default_factory=dict)
    api_key: str | None = None

    @property
    def label(self) -> str:
        return f"{self.provider.name}/{self.model.model}"


@dataclass
class CallResult:
    value: Any
    used: ResolvedModel
    latency_ms: int
    attempts: list[dict]


def litellm_model_name(kind: ProviderKind, model: str, phase: ModelPhase) -> str:
    if kind == ProviderKind.ollama:
        return f"{'ollama' if phase == ModelPhase.embedding else 'ollama_chat'}/{model}"
    if kind == ProviderKind.cloudflare:
        # Workers AI OpenAI-compatible endpoint (/ai/v1) serves both chat and embeddings.
        return f"openai/{model}"
    return f"{PROVIDERS[kind].litellm_prefix}/{model}"


# Provider-specific embedding arguments: NVIDIA retrieval models are asymmetric and need input_type.
def embedding_extra(kind: ProviderKind, input_type: str) -> dict[str, Any]:
    if kind == ProviderKind.nvidia:
        return {"input_type": input_type}
    return {}


def litellm_kwargs(resolved: ResolvedModel) -> dict[str, Any]:
    p = resolved.provider
    settings = get_settings()
    timeout = p.timeout_s or (
        settings.ollama_timeout_s if p.kind == ProviderKind.ollama else settings.provider_timeout_s
    )
    kwargs: dict[str, Any] = {"timeout": timeout, "num_retries": 0}
    if resolved.api_key:
        kwargs["api_key"] = resolved.api_key
    if p.kind == ProviderKind.ollama:
        kwargs["api_base"] = (p.base_url or "").rstrip("/")
    elif p.kind == ProviderKind.cloudflare:
        account = (p.options or {}).get("account_id", "")
        kwargs["api_base"] = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1"
    elif p.base_url:
        kwargs["api_base"] = p.base_url
    return kwargs


async def decrypt_provider_key(session: AsyncSession, provider: Provider) -> str | None:
    if provider.secret_id is None:
        return None
    secret = await session.get(Secret, provider.secret_id)
    if secret is None:
        return None
    return get_secret_box().decrypt(secret.ciphertext, secret.nonce)


class ModelGateway:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _chain_rows(self, phase: ModelPhase, project_id: uuid.UUID | None) -> list[PhaseAssignment]:
        async def rows_for(pid: uuid.UUID | None) -> list[PhaseAssignment]:
            q = select(PhaseAssignment).where(PhaseAssignment.phase == phase)
            q = q.where(
                PhaseAssignment.project_id.is_(None) if pid is None else PhaseAssignment.project_id == pid
            )
            return list((await self.session.scalars(q.order_by(PhaseAssignment.position))).all())

        if project_id is not None:
            override = await rows_for(project_id)
            if override:
                return override
        return await rows_for(None)

    async def _resolve_one(self, model_id: uuid.UUID, params: dict | None = None) -> ResolvedModel | None:
        model = await self.session.get(ProviderModel, model_id)
        if model is None or not model.enabled:
            return None
        provider = await self.session.get(Provider, model.provider_id)
        if provider is None or not provider.enabled:
            return None
        key = await decrypt_provider_key(self.session, provider)
        return ResolvedModel(provider=provider, model=model, params=params or {}, api_key=key)

    async def resolve(
        self,
        phase: ModelPhase,
        project_id: uuid.UUID | None = None,
        selected_model_id: uuid.UUID | None = None,
    ) -> list[ResolvedModel]:
        chain: list[ResolvedModel] = []
        if selected_model_id is not None:
            selected = await self._resolve_one(selected_model_id)
            if selected is None or not supports_phase(selected.model.capabilities, phase):
                raise GatewayError(f"Selected model is not available for phase '{phase.value}'")
            chain.append(selected)
        for row in await self._chain_rows(phase, project_id):
            if any(r.model.id == row.provider_model_id for r in chain):
                continue
            resolved = await self._resolve_one(row.provider_model_id, row.params)
            if resolved is not None:
                chain.append(resolved)
        if phase in SINGLE_MODEL_PHASES:
            chain = chain[:1]
        if not chain:
            raise GatewayError(f"No model configured for phase '{phase.value}'")
        return chain

    async def _run(self, chain: list[ResolvedModel], call) -> CallResult:  # type: ignore[no-untyped-def]
        attempts: list[dict] = []
        for resolved in chain:
            start = time.perf_counter()
            try:
                value = await call(resolved)
            except Exception as exc:  # noqa: BLE001 - any provider failure moves to the next model
                attempts.append(
                    {"model": resolved.label, "error": exc.__class__.__name__, "detail": _safe_detail(exc)}
                )
                continue
            latency = int((time.perf_counter() - start) * 1000)
            attempts.append({"model": resolved.label, "ok": True, "latency_ms": latency})
            return CallResult(value=value, used=resolved, latency_ms=latency, attempts=attempts)
        raise GatewayError("All models in the chain failed", attempts)

    async def complete(
        self,
        phase: ModelPhase,
        messages: list[dict],
        project_id: uuid.UUID | None = None,
        selected_model_id: uuid.UUID | None = None,
        **kwargs: Any,
    ) -> CallResult:
        import litellm

        chain = await self.resolve(phase, project_id, selected_model_id)

        async def call(r: ResolvedModel) -> Any:
            return await litellm.acompletion(
                model=litellm_model_name(r.provider.kind, r.model.model, phase),
                messages=messages,
                **{**r.params, **kwargs},
                **litellm_kwargs(r),
            )

        return await self._run(chain, call)

    async def embed(
        self,
        texts: list[str],
        project_id: uuid.UUID | None = None,
        input_type: str = "passage",
        timeout_s: int | None = None,
    ) -> CallResult:
        """Embed documents (input_type="passage") or a search query (input_type="query").

        `timeout_s` caps the provider timeout, e.g. for interactive searches on a slow provider.
        """
        import litellm

        chain = await self.resolve(ModelPhase.embedding, project_id)

        async def call(r: ResolvedModel) -> list[list[float]]:
            resp = await litellm.aembedding(
                model=litellm_model_name(r.provider.kind, r.model.model, ModelPhase.embedding),
                input=texts,
                **embedding_extra(r.provider.kind, input_type),
                **_capped(litellm_kwargs(r), timeout_s),
            )
            return [d["embedding"] for d in resp.data]

        return await self._run(chain, call)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        project_id: uuid.UUID | None = None,
        top_n: int | None = None,
        timeout_s: int | None = None,
    ) -> CallResult | None:
        """Order documents by relevance. Returns None when no rerank model is configured.

        The value is a list of (document index, relevance score), best first.
        """
        try:
            chain = await self.resolve(ModelPhase.rerank, project_id)
        except GatewayError:
            return None

        async def call(r: ResolvedModel) -> list[tuple[int, float]]:
            kwargs = _capped(litellm_kwargs(r), timeout_s)
            if r.provider.kind == ProviderKind.cloudflare:
                return await _cloudflare_rerank(r, query, documents, top_n, kwargs["timeout"])
            import litellm

            resp = await litellm.arerank(
                model=litellm_model_name(r.provider.kind, r.model.model, ModelPhase.rerank),
                query=query,
                documents=documents,
                top_n=top_n or len(documents),
                **kwargs,
            )
            return [(int(x["index"]), float(x["relevance_score"])) for x in resp.results]

        return await self._run(chain, call)

    async def stream_chat(
        self,
        messages: list[dict],
        project_id: uuid.UUID | None = None,
        selected_model_id: uuid.UUID | None = None,
        first_token_timeout_s: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatEvent]:
        """Stream a chat completion, falling back along the chain until a model starts answering.

        Fallback is only possible before the first token: once text has been streamed to the user, an
        error ends the stream (raised as GatewayError with the partial attempts).
        Yields a `provider` event first, then `token` events, then a final `usage` event.
        """
        import litellm

        chain = await self.resolve(ModelPhase.chat, project_id, selected_model_id)
        attempts: list[dict] = []
        for resolved in chain:
            start = time.perf_counter()
            try:
                stream = await litellm.acompletion(
                    model=litellm_model_name(resolved.provider.kind, resolved.model.model, ModelPhase.chat),
                    messages=messages,
                    stream=True,
                    stream_options={"include_usage": True},
                    **{**resolved.params, **kwargs},
                    **litellm_kwargs(resolved),
                )
                iterator = stream.__aiter__()
                first, usage = await asyncio.wait_for(_first_text(iterator), timeout=first_token_timeout_s)
            except Exception as exc:  # noqa: BLE001 - try the next model of the chain
                attempts.append(
                    {"model": resolved.label, "error": exc.__class__.__name__, "detail": _safe_detail(exc)}
                )
                continue
            attempts.append({"model": resolved.label, "ok": True})
            yield ChatEvent("provider", used=resolved, attempts=attempts)
            if first:
                yield ChatEvent("token", text=first)
            try:
                async for chunk in iterator:
                    text, chunk_usage = _chunk_parts(chunk)
                    usage = chunk_usage or usage
                    if text:
                        yield ChatEvent("token", text=text)
            except Exception as exc:  # noqa: BLE001
                attempts[-1] = {
                    "model": resolved.label,
                    "error": exc.__class__.__name__,
                    "detail": _safe_detail(exc),
                }
                raise GatewayError("The model stopped while answering", attempts) from exc
            latency = int((time.perf_counter() - start) * 1000)
            yield ChatEvent("usage", used=resolved, attempts=attempts, usage=usage, latency_ms=latency)
            return
        raise GatewayError("All chat models in the chain failed", attempts)


@dataclass
class ChatEvent:
    kind: str  # provider | token | usage
    text: str = ""
    used: ResolvedModel | None = None
    attempts: list[dict] = field(default_factory=list)
    usage: dict | None = None
    latency_ms: int | None = None


def _chunk_parts(chunk: Any) -> tuple[str, dict | None]:
    usage = getattr(chunk, "usage", None)
    usage_dict = None
    if usage:
        usage_dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        }
    choices = getattr(chunk, "choices", None) or []
    text = ""
    if choices:
        delta = getattr(choices[0], "delta", None)
        text = (getattr(delta, "content", None) or "") if delta is not None else ""
    return text, usage_dict


async def _first_text(iterator: AsyncIterator[Any]) -> tuple[str, dict | None]:
    """Read until the first non-empty text (reasoning models may stream empty deltas first)."""
    usage = None
    async for chunk in iterator:
        text, chunk_usage = _chunk_parts(chunk)
        usage = chunk_usage or usage
        if text:
            return text, usage
    return "", usage


async def _cloudflare_rerank(
    r: ResolvedModel, query: str, documents: list[str], top_n: int | None, limit_s: float
) -> list[tuple[int, float]]:
    """Workers AI rerank models are not on the OpenAI-compatible endpoint: call /ai/run directly."""
    import httpx

    account = (r.provider.options or {}).get("account_id", "")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{r.model.model}"
    body: dict[str, Any] = {"query": query, "contexts": [{"text": d} for d in documents]}
    if top_n:
        body["top_k"] = top_n
    async with httpx.AsyncClient(timeout=limit_s) as client:
        resp = await client.post(url, json=body, headers={"Authorization": f"Bearer {r.api_key}"})
        resp.raise_for_status()
        items = (resp.json().get("result") or {}).get("response") or []
    return [(int(x["id"]), float(x["score"])) for x in items]


def _capped(kwargs: dict[str, Any], timeout_s: int | None) -> dict[str, Any]:
    if timeout_s is not None:
        kwargs["timeout"] = min(kwargs["timeout"], timeout_s)
    return kwargs


def _safe_detail(exc: Exception) -> str:
    """Short error text with anything that looks like a credential removed."""
    from opennotebook.logging_setup import redact

    return redact(str(exc))[:300]


async def test_model(session: AsyncSession, model: ProviderModel) -> dict:
    """Send a minimal request to a single model (no fallback) and report latency or error."""
    import litellm

    gateway = ModelGateway(session)
    resolved = await gateway._resolve_one(model.id)
    if resolved is None:
        # allow testing models that are not enabled yet
        provider = await session.get(Provider, model.provider_id)
        if provider is None:
            return {"ok": False, "error": "Provider not found"}
        resolved = ResolvedModel(provider, model, api_key=await decrypt_provider_key(session, provider))
    caps = set(model.capabilities)
    start = time.perf_counter()
    try:
        if ModelPhase.embedding in caps:
            resp = await litellm.aembedding(
                model=litellm_model_name(resolved.provider.kind, model.model, ModelPhase.embedding),
                input=["ping"],
                **embedding_extra(resolved.provider.kind, "query"),
                **litellm_kwargs(resolved),
            )
            dim = len(resp.data[0]["embedding"])
            if model.embedding_dim != dim:
                model.embedding_dim = dim
                await session.commit()
            result: dict = {"kind": "embedding", "embedding_dim": dim}
        elif ModelPhase.chat in caps or ModelPhase.vision in caps:
            resp = await litellm.acompletion(
                model=litellm_model_name(resolved.provider.kind, model.model, ModelPhase.chat),
                messages=[{"role": "user", "content": "Reply with the single word OK."}],
                max_tokens=256,  # reasoning models spend tokens before answering
                **litellm_kwargs(resolved),
            )
            result = {"kind": "chat", "reply": (resp.choices[0].message.content or "").strip()[:100]}
        else:
            return {"ok": False, "error": "No connectivity test available for this capability yet"}
    except Exception as exc:  # noqa: BLE001
        status_code = getattr(exc, "status_code", None)
        if status_code in (404, 410):
            # Some catalogs (e.g. NVIDIA) still list retired models: mark them unavailable.
            model.available = False
            await session.commit()
        return {
            "ok": False,
            "error": exc.__class__.__name__,
            "status_code": status_code,
            "detail": _safe_detail(exc),
        }
    return {"ok": True, "latency_ms": int((time.perf_counter() - start) * 1000), **result}
