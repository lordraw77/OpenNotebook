"""Project settings: provider policy (which providers may process the project's content) and the state of
the embedding index that serves searches (US-08)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from opennotebook.acl import get_node_for
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.ingestion.index_state import index_status, settings_row
from opennotebook.models import GrantRole, NodeKind, Provider, ProviderModel

router = APIRouter(prefix="/api/projects", tags=["projects"])


class ProviderPolicyItem(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    enabled: bool
    allowed: bool


class ProjectSettingsOut(BaseModel):
    project_id: uuid.UUID
    restricted: bool
    providers: list[ProviderPolicyItem]
    index: dict


class PolicyIn(BaseModel):
    # null = every provider allowed; a list = only these providers (may be empty: no model calls at all)
    allowed_provider_ids: list[uuid.UUID] | None


async def _project(session: SessionDep, user: CurrentUser, project_id: uuid.UUID, role: GrantRole):  # type: ignore[no-untyped-def]
    node, _ = await get_node_for(session, user, project_id, role)
    if node.kind != NodeKind.project:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Settings belong to a project")
    return node


async def _out(session: SessionDep, project_id: uuid.UUID) -> ProjectSettingsOut:
    row = await settings_row(session, project_id)
    allowed = (
        {uuid.UUID(str(x)) for x in row.allowed_provider_ids}
        if row.allowed_provider_ids is not None
        else None
    )
    providers = (await session.scalars(select(Provider).order_by(Provider.name))).all()
    index = await index_status(session, project_id)
    for key in ("serving_model_id", "configured_model_id"):
        model_id = index.get(key)
        if model_id:
            model = await session.get(ProviderModel, uuid.UUID(model_id))
            provider = await session.get(Provider, model.provider_id) if model else None
            index[key.replace("_id", "")] = f"{provider.name}/{model.model}" if model and provider else None
    await session.commit()
    return ProjectSettingsOut(
        project_id=project_id,
        restricted=allowed is not None,
        providers=[
            ProviderPolicyItem(
                id=p.id,
                name=p.name,
                kind=p.kind.value,
                enabled=p.enabled,
                allowed=allowed is None or p.id in allowed,
            )
            for p in providers
        ],
        index=index,
    )


@router.get("/{project_id}/settings", response_model=ProjectSettingsOut)
async def get_settings(project_id: uuid.UUID, user: CurrentUser, session: SessionDep) -> ProjectSettingsOut:
    await _project(session, user, project_id, GrantRole.viewer)
    return await _out(session, project_id)


@router.put("/{project_id}/policy", response_model=ProjectSettingsOut)
async def put_policy(
    project_id: uuid.UUID, body: PolicyIn, user: CurrentUser, session: SessionDep
) -> ProjectSettingsOut:
    """Restrict the providers that may receive this project's content (owners only)."""
    await _project(session, user, project_id, GrantRole.owner)
    ids = None
    if body.allowed_provider_ids is not None:
        known = set((await session.scalars(select(Provider.id))).all())
        unknown = [str(i) for i in body.allowed_provider_ids if i not in known]
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown providers: {', '.join(unknown)}"
            )
        ids = sorted({str(i) for i in body.allowed_provider_ids})
    row = await settings_row(session, project_id)
    row.allowed_provider_ids = ids
    audit(session, user, "project.policy", "node", project_id, allowed_provider_ids=ids)
    await session.commit()
    return await _out(session, project_id)
