"""Provider registry operations: credentials, model sync, phase assignments, bootstrap from environment."""

from __future__ import annotations

import logging
import os
import uuid
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.config import get_settings
from opennotebook.crypto import get_secret_box, secret_hint
from opennotebook.models import (
    ModelPhase,
    Node,
    NodeKind,
    PhaseAssignment,
    Provider,
    ProviderKind,
    ProviderModel,
    Secret,
)
from opennotebook.providers.catalog import (
    PROVIDERS,
    SINGLE_MODEL_PHASES,
    ProviderError,
    list_models,
    supports_phase,
)
from opennotebook.providers.gateway import decrypt_provider_key

log = logging.getLogger(__name__)


class AssignmentError(ValueError):
    pass


def _clip(value: str | None, limit: int = 300) -> str | None:
    return value[:limit] if value else None


async def store_secret(session: AsyncSession, value: str) -> Secret:
    ciphertext, nonce = get_secret_box().encrypt(value)
    secret = Secret(ciphertext=ciphertext, nonce=nonce, hint=secret_hint(value))
    session.add(secret)
    await session.flush()
    return secret


async def set_provider_key(session: AsyncSession, provider: Provider, api_key: str | None) -> None:
    old = provider.secret_id
    if api_key:
        provider.secret_id = (await store_secret(session, api_key)).id
    else:
        provider.secret_id = None
    if old is not None:
        await session.execute(delete(Secret).where(Secret.id == old))


async def key_hint(session: AsyncSession, provider: Provider) -> str | None:
    if provider.secret_id is None:
        return None
    secret = await session.get(Secret, provider.secret_id)
    return secret.hint if secret else None


async def sync_models(
    session: AsyncSession, provider: Provider, client: httpx.AsyncClient | None = None
) -> dict[str, int]:
    """Refresh the provider's model catalog. Manual capability overrides and enabled flags are preserved."""
    api_key = await decrypt_provider_key(session, provider)
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        discovered = await list_models(
            provider.kind,
            api_key=api_key,
            base_url=provider.base_url,
            options=provider.options or {},
            client=client,
        )
    except ProviderError as exc:
        provider.last_error = str(exc)
        await session.commit()
        raise
    finally:
        if own_client:
            await client.aclose()

    existing = {
        m.model: m
        for m in (
            await session.scalars(select(ProviderModel).where(ProviderModel.provider_id == provider.id))
        ).all()
    }
    seen: set[str] = set()
    added = updated = 0
    for d in discovered:
        if d.model in seen:
            continue
        seen.add(d.model)
        row = existing.get(d.model)
        if row is None:
            session.add(
                ProviderModel(
                    provider_id=provider.id,
                    model=d.model,
                    display_name=_clip(d.display_name),
                    capabilities=sorted(d.capabilities),
                    capabilities_source=d.source,
                    context_window=d.context_window,
                    embedding_dim=d.embedding_dim,
                    enabled=False,
                    available=True,
                )
            )
            added += 1
        else:
            row.available = True
            row.display_name = _clip(d.display_name) or row.display_name
            row.context_window = d.context_window or row.context_window
            if row.capabilities_source != "manual":
                row.capabilities = sorted(d.capabilities)
                row.capabilities_source = d.source
            updated += 1
    missing = 0
    for name, row in existing.items():
        if name not in seen and row.available:
            row.available = False
            missing += 1
    provider.last_sync_at = datetime.now(UTC)
    provider.last_error = None
    await session.commit()
    return {"discovered": len(seen), "added": added, "updated": updated, "unavailable": missing}


async def set_assignment(
    session: AsyncSession,
    phase: ModelPhase,
    model_ids: list[uuid.UUID],
    project_id: uuid.UUID | None,
    params: list[dict] | None = None,
) -> list[PhaseAssignment]:
    """Replace the chain for (phase, project).

    An empty list removes it: the project then falls back to the global chain.
    """
    if phase in SINGLE_MODEL_PHASES and len(model_ids) > 1:
        raise AssignmentError(f"Phase '{phase.value}' takes exactly one model (no fallback)")
    if len(set(model_ids)) != len(model_ids):
        raise AssignmentError("A model appears more than once in the chain")
    if project_id is not None:
        project = await session.get(Node, project_id)
        if project is None or project.kind != NodeKind.project or project.deleted_at is not None:
            raise AssignmentError("project_id must reference a project")
    for mid in model_ids:
        model = await session.get(ProviderModel, mid)
        if model is None:
            raise AssignmentError(f"Unknown model {mid}")
        if not model.enabled:
            raise AssignmentError(f"Model '{model.model}' is not enabled")
        if not supports_phase(model.capabilities, phase):
            raise AssignmentError(f"Model '{model.model}' does not support phase '{phase.value}'")

    q = delete(PhaseAssignment).where(PhaseAssignment.phase == phase)
    q = q.where(
        PhaseAssignment.project_id.is_(None)
        if project_id is None
        else PhaseAssignment.project_id == project_id
    )
    await session.execute(q)
    rows = [
        PhaseAssignment(
            phase=phase,
            project_id=project_id,
            position=i,
            provider_model_id=mid,
            params=(params[i] if params and i < len(params) else {}),
        )
        for i, mid in enumerate(model_ids)
    ]
    session.add_all(rows)
    await session.flush()
    return rows


# --- bootstrap from environment ------------------------------------------------------------------

_PHASE_ENV = {
    ModelPhase.chat: "MODEL_CHAT",
    ModelPhase.summary: "MODEL_SUMMARY",
    ModelPhase.graph_extraction: "MODEL_GRAPH_EXTRACTION",
    ModelPhase.vision: "MODEL_VISION",
    ModelPhase.ocr: "MODEL_OCR",
    ModelPhase.embedding: "MODEL_EMBEDDING",
    ModelPhase.rerank: "MODEL_RERANK",
}


async def import_providers_from_env(session: AsyncSession) -> list[str]:
    """Create providers for every key present in the environment, if not registered yet."""
    created: list[str] = []
    settings = get_settings()
    for kind, spec in PROVIDERS.items():
        exists = await session.scalar(select(Provider).where(Provider.kind == kind))
        if exists is not None:
            continue
        api_key = os.environ.get(spec.env_api_key, "") if spec.env_api_key else ""
        base_url = os.environ.get(spec.env_base_url, "") if spec.env_base_url else ""
        if spec.requires_api_key and not api_key:
            continue
        if spec.requires_base_url and not base_url:
            continue
        options = {k: os.environ.get(env, "") for k, env in spec.env_options.items()}
        timeout = settings.ollama_timeout_s if kind == ProviderKind.ollama else settings.provider_timeout_s
        provider = Provider(
            kind=kind, name=kind.value, base_url=base_url or None, options=options, timeout_s=timeout
        )
        session.add(provider)
        await session.flush()
        if api_key:
            await set_provider_key(session, provider, api_key)
        created.append(kind.value)
    await session.commit()
    return created


async def import_assignments_from_env(session: AsyncSession) -> dict[str, str]:
    """Apply MODEL_<PHASE>=provider/model[,provider/model] defaults when the global chain is empty.

    Requires the provider models to be synced; referenced models are enabled automatically.
    """
    results: dict[str, str] = {}
    for phase, env in _PHASE_ENV.items():
        spec = os.environ.get(env, "").strip()
        if not spec:
            continue
        has_chain = await session.scalar(
            select(PhaseAssignment.id).where(
                PhaseAssignment.phase == phase, PhaseAssignment.project_id.is_(None)
            )
        )
        if has_chain:
            results[phase.value] = "kept existing"
            continue
        ids: list[uuid.UUID] = []
        for item in [s.strip() for s in spec.split(",") if s.strip()]:
            provider_name, _, model_name = item.partition("/")
            model = await session.scalar(
                select(ProviderModel)
                .join(Provider, Provider.id == ProviderModel.provider_id)
                .where(Provider.name == provider_name, ProviderModel.model == model_name)
            )
            if model is None:
                results[phase.value] = f"model not found: {item}"
                ids = []
                break
            model.enabled = True
            ids.append(model.id)
        if ids:
            try:
                await set_assignment(session, phase, ids, None)
                results[phase.value] = "configured"
            except AssignmentError as exc:
                results[phase.value] = str(exc)
    await session.commit()
    return results
