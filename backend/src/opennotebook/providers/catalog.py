"""Provider metadata and model discovery.

Each provider exposes a model listing endpoint. Capabilities are taken from provider metadata when available
(Gemini, Mistral, OpenRouter, Cloudflare, Ollama) and otherwise inferred from the model id. Administrators can
override capabilities manually; manual values are never overwritten by a later sync.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

import httpx

from opennotebook.models import ModelPhase, ProviderKind

# Capabilities stored on models. Phases map to the capability they require (see PHASE_REQUIREMENTS).
CHAT, VISION, EMBEDDING, RERANK, OCR = (
    ModelPhase.chat,
    ModelPhase.vision,
    ModelPhase.embedding,
    ModelPhase.rerank,
    ModelPhase.ocr,
)

PHASE_REQUIREMENTS: dict[ModelPhase, set[ModelPhase]] = {
    ModelPhase.chat: {CHAT},
    ModelPhase.summary: {CHAT},
    ModelPhase.graph_extraction: {CHAT},
    ModelPhase.vision: {VISION},
    ModelPhase.ocr: {OCR, VISION},  # dedicated OCR model, or a vision model prompted for transcription
    ModelPhase.embedding: {EMBEDDING},
    ModelPhase.rerank: {RERANK},
}

SINGLE_MODEL_PHASES = {ModelPhase.embedding}  # vectors from different models are not comparable


def supports_phase(capabilities: list[ModelPhase] | set[ModelPhase], phase: ModelPhase) -> bool:
    return bool(set(capabilities) & PHASE_REQUIREMENTS[phase])


@dataclass(frozen=True)
class ProviderSpec:
    kind: ProviderKind
    label: str
    litellm_prefix: str
    env_api_key: str | None
    requires_api_key: bool = True
    requires_base_url: bool = False
    option_keys: tuple[str, ...] = ()
    env_options: dict[str, str] = field(default_factory=dict)
    env_base_url: str | None = None


PROVIDERS: dict[ProviderKind, ProviderSpec] = {
    s.kind: s
    for s in [
        ProviderSpec(ProviderKind.groq, "Groq", "groq", "GROQ_API_KEY"),
        ProviderSpec(ProviderKind.openrouter, "OpenRouter", "openrouter", "OPENROUTER_API_KEY"),
        ProviderSpec(ProviderKind.gemini, "Google Gemini", "gemini", "GEMINI_API_KEY"),
        ProviderSpec(
            ProviderKind.cloudflare,
            "Cloudflare Workers AI",
            "cloudflare",
            "CLOUDFLARE_API_KEY",
            option_keys=("account_id",),
            env_options={"account_id": "CLOUDFLARE_ACCOUNT_ID"},
        ),
        ProviderSpec(ProviderKind.cerebras, "Cerebras", "cerebras", "CEREBRAS_API_KEY"),
        ProviderSpec(ProviderKind.mistral, "Mistral", "mistral", "MISTRAL_API_KEY"),
        ProviderSpec(ProviderKind.nvidia, "NVIDIA NIM", "nvidia_nim", "NVIDIA_API_KEY"),
        ProviderSpec(ProviderKind.huggingface, "Hugging Face", "huggingface", "HF_TOKEN"),
        ProviderSpec(
            ProviderKind.ollama,
            "Ollama",
            "ollama_chat",
            None,
            requires_api_key=False,
            requires_base_url=True,
            env_base_url="OLLAMA_API_BASE",
        ),
    ]
}


@dataclass
class DiscoveredModel:
    model: str
    display_name: str | None = None
    capabilities: set[ModelPhase] = field(default_factory=set)
    source: str = "inferred"  # inferred | provider
    context_window: int | None = None
    embedding_dim: int | None = None


class ProviderError(Exception):
    pass


# --- capability inference from model ids -------------------------------------------------------

_NOT_TEXT = re.compile(
    r"whisper|tts|playai|orpheus|speech|audio|transcri|guard|safety|moderation|"
    r"stable-diffusion|flux|sdxl|dall-?e|imagen|veo|image-generation|-image-|lyria|"
    r"detr|resnet|yolo|segment|depth|-vad",
    re.I,
)
_EMBED = re.compile(r"embed|e5-|bge-(?!reranker)|gte-|nomic-embed|arctic-embed|retriever|nv-embed", re.I)
_RERANK = re.compile(r"rerank", re.I)
_OCR = re.compile(r"\bocr\b|-ocr|ocr-", re.I)
_VISION = re.compile(
    r"vision|-vl\b|-vl-|vl-|pixtral|llava|llama-4|scout|maverick|gemma-3|gemma3|gemini|vila|neva|"
    r"multimodal|omni|mistral-small-3|mistral-medium|kimi-vl|qwen2\.5-vl|qwen3-vl|phi-4-multimodal",
    re.I,
)


def infer_capabilities(model_id: str) -> set[ModelPhase]:
    if _NOT_TEXT.search(model_id):
        return set()
    if _RERANK.search(model_id):
        return {RERANK}
    if _EMBED.search(model_id):
        return {EMBEDDING}
    if _OCR.search(model_id):
        return {OCR}
    caps = {CHAT}
    if _VISION.search(model_id):
        caps.add(VISION)
    return caps


# --- listing per provider ----------------------------------------------------------------------


async def _get_json(client: httpx.AsyncClient, url: str, **kwargs: object) -> dict:
    try:
        resp = await client.get(url, **kwargs)  # type: ignore[arg-type]
    except httpx.HTTPError as exc:
        raise ProviderError(f"Connection failed: {exc.__class__.__name__}") from exc
    if resp.status_code in (401, 403):
        raise ProviderError(f"Authentication failed (HTTP {resp.status_code})")
    if resp.status_code >= 400:
        raise ProviderError(f"HTTP {resp.status_code} from model listing endpoint")
    return resp.json()


def _bearer(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


async def _openai_compatible(
    client: httpx.AsyncClient, url: str, api_key: str | None
) -> list[DiscoveredModel]:
    data = await _get_json(client, url, headers=_bearer(api_key))
    out = []
    for m in data.get("data", []):
        mid = m["id"]
        out.append(
            DiscoveredModel(
                model=mid,
                capabilities=infer_capabilities(mid),
                context_window=m.get("context_window") or m.get("context_length") or m.get("max_model_len"),
            )
        )
    return out


async def _openrouter(client: httpx.AsyncClient, api_key: str | None) -> list[DiscoveredModel]:
    data = await _get_json(client, "https://openrouter.ai/api/v1/models", headers=_bearer(api_key))
    out: list[DiscoveredModel] = []
    for m in data.get("data", []):
        arch = m.get("architecture") or {}
        inputs = set(arch.get("input_modalities") or [])
        outputs = set(arch.get("output_modalities") or ["text"])
        caps: set[ModelPhase] = set()
        if "text" in outputs:
            caps.add(CHAT)
            if "image" in inputs:
                caps.add(VISION)
        out.append(
            DiscoveredModel(
                model=m["id"],
                display_name=m.get("name"),
                capabilities=caps,
                source="provider",
                context_window=m.get("context_length"),
            )
        )
    # Embedding models are listed on a separate endpoint; tolerate its absence.
    try:
        emb = await _get_json(
            client, "https://openrouter.ai/api/v1/embeddings/models", headers=_bearer(api_key)
        )
        for m in emb.get("data", []):
            out.append(
                DiscoveredModel(
                    model=m["id"],
                    display_name=m.get("name"),
                    capabilities={EMBEDDING},
                    source="provider",
                    context_window=m.get("context_length"),
                )
            )
    except ProviderError:
        pass
    return out


async def _gemini(client: httpx.AsyncClient, api_key: str | None) -> list[DiscoveredModel]:
    out: list[DiscoveredModel] = []
    page_token = None
    while True:
        params = {"pageSize": "1000"}
        if page_token:
            params["pageToken"] = page_token
        data = await _get_json(
            client,
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": api_key or ""},
            params=params,
        )
        for m in data.get("models", []):
            mid = m["name"].removeprefix("models/")
            methods = set(m.get("supportedGenerationMethods") or [])
            caps: set[ModelPhase] = set()
            if "embedContent" in methods:
                caps.add(EMBEDDING)
            if "generateContent" in methods and not _NOT_TEXT.search(mid):
                caps |= {CHAT, VISION} if "gemini" in mid or "gemma-3" in mid else {CHAT}
            out.append(
                DiscoveredModel(
                    model=mid,
                    display_name=m.get("displayName"),
                    capabilities=caps,
                    source="provider",
                    context_window=m.get("inputTokenLimit"),
                )
            )
        page_token = data.get("nextPageToken")
        if not page_token:
            return out


async def _mistral(client: httpx.AsyncClient, api_key: str | None) -> list[DiscoveredModel]:
    data = await _get_json(client, "https://api.mistral.ai/v1/models", headers=_bearer(api_key))
    out: list[DiscoveredModel] = []
    seen: set[str] = set()
    for m in data.get("data", []):
        mid = m["id"]
        if mid in seen:
            continue
        seen.add(mid)
        c = m.get("capabilities") or {}
        caps: set[ModelPhase] = set()
        if "embed" in mid:
            caps.add(EMBEDDING)
        elif c.get("ocr") or "ocr" in mid:
            caps.add(OCR)
        elif c.get("completion_chat") and not _NOT_TEXT.search(mid):
            caps.add(CHAT)
            if c.get("vision"):
                caps.add(VISION)
        out.append(
            DiscoveredModel(
                model=mid,
                display_name=m.get("name"),
                capabilities=caps,
                source="provider",
                context_window=m.get("max_context_length"),
            )
        )
    return out


_CF_TASKS = {
    "Text Generation": {CHAT},
    "Text Embeddings": {EMBEDDING},
    "Image-to-Text": {VISION},
}


async def _cloudflare(
    client: httpx.AsyncClient, api_key: str | None, account_id: str
) -> list[DiscoveredModel]:
    if not account_id:
        raise ProviderError("Cloudflare requires an account_id option")
    out: list[DiscoveredModel] = []
    page = 1
    while True:
        data = await _get_json(
            client,
            f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/models/search",
            headers=_bearer(api_key),
            params={"per_page": "100", "page": str(page)},
        )
        results = data.get("result") or []
        for m in results:
            name = m["name"]
            task = (m.get("task") or {}).get("name", "")
            caps = set(_CF_TASKS.get(task, set()))
            if "rerank" in name:
                caps = {RERANK}
            elif CHAT in caps and _VISION.search(name):
                caps.add(VISION)
            out.append(DiscoveredModel(model=name, display_name=None, capabilities=caps, source="provider"))
        info = data.get("result_info") or {}
        if not results or page * int(info.get("per_page", 100)) >= int(info.get("total_count", 0)):
            return out
        page += 1


async def _ollama(client: httpx.AsyncClient, base_url: str) -> list[DiscoveredModel]:
    base = base_url.rstrip("/")
    data = await _get_json(client, f"{base}/api/tags")
    names = [m["name"] for m in data.get("models", [])]
    sem = asyncio.Semaphore(4)

    async def show(name: str) -> DiscoveredModel:
        async with sem:
            try:
                resp = await client.post(f"{base}/api/show", json={"model": name})
                info = resp.json() if resp.status_code == 200 else {}
            except (httpx.HTTPError, ValueError):
                info = {}
        reported = set(info.get("capabilities") or [])
        if not reported:
            return DiscoveredModel(model=name, capabilities=infer_capabilities(name))
        caps: set[ModelPhase] = set()
        if "embedding" in reported:
            caps.add(EMBEDDING)
        if "completion" in reported:
            caps.add(CHAT)
        if "vision" in reported:
            caps.add(VISION)
        ctx = None
        for key, value in (info.get("model_info") or {}).items():
            if key.endswith(".context_length"):
                ctx = value
        return DiscoveredModel(model=name, capabilities=caps, source="provider", context_window=ctx)

    return list(await asyncio.gather(*(show(n) for n in names)))


async def list_models(
    kind: ProviderKind,
    *,
    api_key: str | None,
    base_url: str | None,
    options: dict,
    client: httpx.AsyncClient,
) -> list[DiscoveredModel]:
    match kind:
        case ProviderKind.groq:
            return await _openai_compatible(client, "https://api.groq.com/openai/v1/models", api_key)
        case ProviderKind.cerebras:
            return await _openai_compatible(client, "https://api.cerebras.ai/v1/models", api_key)
        case ProviderKind.nvidia:
            return await _openai_compatible(client, "https://integrate.api.nvidia.com/v1/models", api_key)
        case ProviderKind.huggingface:
            return await _openai_compatible(client, "https://router.huggingface.co/v1/models", api_key)
        case ProviderKind.openrouter:
            return await _openrouter(client, api_key)
        case ProviderKind.gemini:
            return await _gemini(client, api_key)
        case ProviderKind.mistral:
            return await _mistral(client, api_key)
        case ProviderKind.cloudflare:
            return await _cloudflare(client, api_key, str(options.get("account_id", "")))
        case ProviderKind.ollama:
            if not base_url:
                raise ProviderError("Ollama requires a base URL")
            return await _ollama(client, base_url)
    raise ProviderError(f"Unsupported provider {kind}")
