"""Provider registry and model catalog (administrators only)."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from opennotebook.deps import AdminUser, SessionDep, audit
from opennotebook.models import ModelPhase, PhaseAssignment, Provider, ProviderKind, ProviderModel
from opennotebook.providers.catalog import PROVIDERS, ProviderError
from opennotebook.providers.gateway import test_model
from opennotebook.providers.service import key_hint, set_provider_key, sync_models

router = APIRouter(prefix="/api", tags=["providers"])

BASE_CAPABILITIES = {
    ModelPhase.chat,
    ModelPhase.vision,
    ModelPhase.embedding,
    ModelPhase.rerank,
    ModelPhase.ocr,
}


class ProviderKindOut(BaseModel):
    kind: ProviderKind
    label: str
    requires_api_key: bool
    requires_base_url: bool
    option_keys: list[str]


class ProviderOut(BaseModel):
    id: uuid.UUID
    kind: ProviderKind
    label: str
    name: str
    base_url: str | None
    options: dict
    enabled: bool
    timeout_s: int
    api_key_hint: str | None
    last_sync_at: datetime | None
    last_error: str | None
    model_count: int
    enabled_model_count: int


class ProviderCreate(BaseModel):
    kind: ProviderKind
    name: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    api_key: str | None = Field(default=None, max_length=4096)
    base_url: str | None = Field(default=None, max_length=2048)
    options: dict[str, str] = Field(default_factory=dict)
    timeout_s: int = Field(default=60, ge=5, le=3600)

    @field_validator("base_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.startswith(("http://", "https://")):
            raise ValueError("base_url must start with http:// or https://")
        return v


class ProviderUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=4096, description="Empty string removes the key")
    base_url: str | None = Field(default=None, max_length=2048)
    options: dict[str, str] | None = None
    enabled: bool | None = None
    timeout_s: int | None = Field(default=None, ge=5, le=3600)


class ModelOut(BaseModel):
    id: uuid.UUID
    provider_id: uuid.UUID
    provider_name: str
    provider_kind: ProviderKind
    model: str
    display_name: str | None
    capabilities: list[ModelPhase]
    capabilities_source: str
    context_window: int | None
    embedding_dim: int | None
    enabled: bool
    available: bool


class ModelCreate(BaseModel):
    model: str = Field(min_length=1, max_length=300)
    capabilities: list[ModelPhase]
    display_name: str | None = None


class ModelUpdate(BaseModel):
    enabled: bool | None = None
    capabilities: list[ModelPhase] | None = None


def _validate_caps(caps: list[ModelPhase]) -> list[ModelPhase]:
    bad = set(caps) - BASE_CAPABILITIES
    if bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Capabilities must be among {sorted(c.value for c in BASE_CAPABILITIES)}",
        )
    return sorted(set(caps))


async def _provider_out(session: SessionDep, p: Provider) -> ProviderOut:
    total = await session.scalar(select(func.count()).where(ProviderModel.provider_id == p.id))
    enabled = await session.scalar(
        select(func.count()).where(ProviderModel.provider_id == p.id, ProviderModel.enabled.is_(True))
    )
    return ProviderOut(
        id=p.id,
        kind=p.kind,
        label=PROVIDERS[p.kind].label,
        name=p.name,
        base_url=p.base_url,
        options=p.options or {},
        enabled=p.enabled,
        timeout_s=p.timeout_s,
        api_key_hint=await key_hint(session, p),
        last_sync_at=p.last_sync_at,
        last_error=p.last_error,
        model_count=total or 0,
        enabled_model_count=enabled or 0,
    )


def model_out(m: ProviderModel, p: Provider) -> ModelOut:
    return ModelOut(
        id=m.id,
        provider_id=p.id,
        provider_name=p.name,
        provider_kind=p.kind,
        model=m.model,
        display_name=m.display_name,
        capabilities=list(m.capabilities),
        capabilities_source=m.capabilities_source,
        context_window=m.context_window,
        embedding_dim=m.embedding_dim,
        enabled=m.enabled,
        available=m.available,
    )


async def _get_provider(session: SessionDep, provider_id: uuid.UUID) -> Provider:
    p = await session.get(Provider, provider_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    return p


@router.get("/provider-kinds", response_model=list[ProviderKindOut])
async def provider_kinds(_: AdminUser) -> list[ProviderKindOut]:
    return [
        ProviderKindOut(
            kind=s.kind,
            label=s.label,
            requires_api_key=s.requires_api_key,
            requires_base_url=s.requires_base_url,
            option_keys=list(s.option_keys),
        )
        for s in PROVIDERS.values()
    ]


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(_: AdminUser, session: SessionDep) -> list[ProviderOut]:
    providers = (await session.scalars(select(Provider).order_by(Provider.name))).all()
    return [await _provider_out(session, p) for p in providers]


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderCreate, admin: AdminUser, session: SessionDep) -> ProviderOut:
    spec = PROVIDERS[body.kind]
    if spec.requires_api_key and not body.api_key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{spec.label} requires an API key")
    if spec.requires_base_url and not body.base_url:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"{spec.label} requires a base URL")
    missing = [k for k in spec.option_keys if not body.options.get(k)]
    if missing:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Missing options: {', '.join(missing)}")
    provider = Provider(
        kind=body.kind,
        name=body.name,
        base_url=body.base_url,
        options={k: body.options[k] for k in spec.option_keys},
        timeout_s=body.timeout_s,
    )
    session.add(provider)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider name already used") from exc
    if body.api_key:
        await set_provider_key(session, provider, body.api_key)
    audit(session, admin, "provider.create", "provider", provider.id, kind=body.kind.value, name=body.name)
    await session.commit()
    return await _provider_out(session, provider)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: uuid.UUID, body: ProviderUpdate, admin: AdminUser, session: SessionDep
) -> ProviderOut:
    p = await _get_provider(session, provider_id)
    changes = body.model_dump(exclude_unset=True)
    if "api_key" in changes:
        await set_provider_key(session, p, body.api_key or None)
        changes["api_key"] = "changed" if body.api_key else "removed"
    if body.base_url is not None:
        p.base_url = body.base_url or None
    if body.options is not None:
        p.options = {k: body.options.get(k, "") for k in PROVIDERS[p.kind].option_keys}
    if body.enabled is not None:
        p.enabled = body.enabled
    if body.timeout_s is not None:
        p.timeout_s = body.timeout_s
    audit(session, admin, "provider.update", "provider", p.id, **{k: str(v) for k, v in changes.items()})
    await session.commit()
    return await _provider_out(session, p)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> None:
    p = await _get_provider(session, provider_id)
    in_use = await session.scalar(
        select(func.count())
        .select_from(PhaseAssignment)
        .join(ProviderModel, ProviderModel.id == PhaseAssignment.provider_model_id)
        .where(ProviderModel.provider_id == p.id)
    )
    if in_use:
        raise HTTPException(status.HTTP_409_CONFLICT, "Provider models are used in phase assignments")
    await set_provider_key(session, p, None)
    await session.delete(p)
    audit(session, admin, "provider.delete", "provider", provider_id, name=p.name)
    await session.commit()


@router.post("/providers/{provider_id}/sync")
async def sync_provider(provider_id: uuid.UUID, admin: AdminUser, session: SessionDep) -> dict:
    p = await _get_provider(session, provider_id)
    try:
        result = await sync_models(session, p)
    except ProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    audit(session, admin, "provider.sync", "provider", p.id, **result)
    await session.commit()
    return result


@router.get("/providers/{provider_id}/models", response_model=list[ModelOut])
async def list_provider_models(
    provider_id: uuid.UUID,
    _: AdminUser,
    session: SessionDep,
    capability: ModelPhase | None = None,
    q: str = "",
    enabled_only: bool = False,
) -> list[ModelOut]:
    p = await _get_provider(session, provider_id)
    stmt = select(ProviderModel).where(ProviderModel.provider_id == p.id).order_by(ProviderModel.model)
    if capability is not None:
        stmt = stmt.where(ProviderModel.capabilities.any(capability))
    if q:
        stmt = stmt.where(func.lower(ProviderModel.model).contains(q.lower()))
    if enabled_only:
        stmt = stmt.where(ProviderModel.enabled.is_(True))
    return [model_out(m, p) for m in (await session.scalars(stmt)).all()]


@router.post("/providers/{provider_id}/models", response_model=ModelOut, status_code=201)
async def add_model(
    provider_id: uuid.UUID, body: ModelCreate, admin: AdminUser, session: SessionDep
) -> ModelOut:
    """Register a model the provider does not list (e.g. a Hugging Face embedding model)."""
    p = await _get_provider(session, provider_id)
    m = ProviderModel(
        provider_id=p.id,
        model=body.model,
        display_name=body.display_name,
        capabilities=_validate_caps(body.capabilities),
        capabilities_source="manual",
        enabled=True,
    )
    session.add(m)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Model already registered") from exc
    audit(session, admin, "model.create", "provider_model", m.id, model=m.model)
    await session.commit()
    return model_out(m, p)


@router.patch("/provider-models/{model_id}", response_model=ModelOut)
async def update_model(
    model_id: uuid.UUID, body: ModelUpdate, admin: AdminUser, session: SessionDep
) -> ModelOut:
    m = await session.get(ProviderModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    if body.enabled is False:
        used = await session.scalar(select(func.count()).where(PhaseAssignment.provider_model_id == m.id))
        if used:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Model is used in a phase assignment; remove it first"
            )
    if body.enabled is not None:
        m.enabled = body.enabled
    if body.capabilities is not None:
        m.capabilities = _validate_caps(body.capabilities)
        m.capabilities_source = "manual"
    audit(
        session,
        admin,
        "model.update",
        "provider_model",
        m.id,
        **body.model_dump(exclude_unset=True, mode="json"),
    )
    await session.commit()
    p = await session.get(Provider, m.provider_id)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Provider not found")
    return model_out(m, p)


@router.post("/provider-models/{model_id}/test")
async def test_provider_model(model_id: uuid.UUID, _: AdminUser, session: SessionDep) -> dict:
    m = await session.get(ProviderModel, model_id)
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    return await test_model(session, m)
