"""Model selection per phase: global defaults, per-project overrides, and models selectable by users."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from opennotebook.acl import get_node_for
from opennotebook.api.providers import ModelOut, model_out
from opennotebook.deps import CurrentUser, SessionDep, audit
from opennotebook.models import GrantRole, ModelPhase, NodeKind, PhaseAssignment, Provider, ProviderModel
from opennotebook.providers.catalog import PHASE_REQUIREMENTS, SINGLE_MODEL_PHASES
from opennotebook.providers.service import AssignmentError, set_assignment

router = APIRouter(prefix="/api", tags=["models"])


class ChainItem(BaseModel):
    position: int
    model: ModelOut
    params: dict


class PhaseOut(BaseModel):
    phase: ModelPhase
    single_model: bool
    required_capabilities: list[ModelPhase]
    global_chain: list[ChainItem]
    project_chain: list[ChainItem] | None = None
    effective: list[ChainItem]
    source: str  # "project" | "global" | "none"


class AssignmentIn(BaseModel):
    project_id: uuid.UUID | None = None
    model_ids: list[uuid.UUID] = Field(max_length=8)
    params: list[dict] | None = None


async def _chain(session: SessionDep, phase: ModelPhase, project_id: uuid.UUID | None) -> list[ChainItem]:
    stmt = (
        select(PhaseAssignment, ProviderModel, Provider)
        .join(ProviderModel, ProviderModel.id == PhaseAssignment.provider_model_id)
        .join(Provider, Provider.id == ProviderModel.provider_id)
        .where(PhaseAssignment.phase == phase)
        .order_by(PhaseAssignment.position)
    )
    stmt = stmt.where(
        PhaseAssignment.project_id.is_(None)
        if project_id is None
        else PhaseAssignment.project_id == project_id
    )
    return [
        ChainItem(position=a.position, model=model_out(m, p), params=a.params or {})
        for a, m, p in (await session.execute(stmt)).all()
    ]


async def _require_project(session: SessionDep, user, project_id: uuid.UUID, role: GrantRole):  # type: ignore[no-untyped-def]
    node, _ = await get_node_for(session, user, project_id, role)
    if node.kind != NodeKind.project:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "project_id must reference a project")
    return node


@router.get("/model-assignments", response_model=list[PhaseOut])
async def get_assignments(
    user: CurrentUser, session: SessionDep, project_id: uuid.UUID | None = None
) -> list[PhaseOut]:
    if project_id is not None:
        await _require_project(session, user, project_id, GrantRole.viewer)
    out = []
    for phase in ModelPhase:
        global_chain = await _chain(session, phase, None)
        project_chain = await _chain(session, phase, project_id) if project_id else None
        if project_chain:
            effective, source = project_chain, "project"
        else:
            effective, source = global_chain, ("global" if global_chain else "none")
        out.append(
            PhaseOut(
                phase=phase,
                single_model=phase in SINGLE_MODEL_PHASES,
                required_capabilities=sorted(PHASE_REQUIREMENTS[phase]),
                global_chain=global_chain,
                project_chain=project_chain,
                effective=effective,
                source=source,
            )
        )
    return out


@router.put("/model-assignments/{phase}", response_model=PhaseOut)
async def put_assignment(
    phase: ModelPhase, body: AssignmentIn, user: CurrentUser, session: SessionDep
) -> PhaseOut:
    """Global chains need an administrator; a project override needs the owner role on the project."""
    if body.project_id is None:
        if not user.is_admin:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Administrator role required for global defaults")
    else:
        await _require_project(session, user, body.project_id, GrantRole.owner)

    previous = await _chain(session, phase, body.project_id)
    try:
        await set_assignment(session, phase, body.model_ids, body.project_id, body.params)
    except AssignmentError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    audit(
        session,
        user,
        "model_assignment.put",
        "phase",
        phase.value,
        project_id=str(body.project_id) if body.project_id else None,
        model_ids=[str(m) for m in body.model_ids],
        previous=[str(c.model.id) for c in previous],
    )
    await session.commit()
    result = next(p for p in await get_assignments(user, session, body.project_id) if p.phase == phase)
    return result


@router.get("/models/selectable", response_model=list[ModelOut])
async def selectable_models(
    phase: ModelPhase,
    user: CurrentUser,
    session: SessionDep,
    project_id: uuid.UUID | None = None,
    include_all: bool = False,
) -> list[ModelOut]:
    """Enabled models a user may pick for a phase (e.g. the chat model selector in the Workbench).

    The effective chain comes first, in order, followed by the other enabled models with the capability.
    For single-model phases (embedding) only the configured model is returned, because it is fixed per
    index; `include_all=true` lists every candidate, for the configuration screens.
    """
    if project_id is not None:
        # Anyone who can chat in the project (even with access to a single workspace inside it) may list
        # the models; the same rule as searching the project scope.
        from opennotebook.acl import get_search_scope

        node = await get_search_scope(session, user, project_id)
        if node.kind != NodeKind.project:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "project_id must reference a project")
    chain = await _chain(session, phase, project_id) if project_id else []
    if not chain:
        chain = await _chain(session, phase, None)
    if phase in SINGLE_MODEL_PHASES and not include_all:
        return [c.model for c in chain]
    ordered = [c.model for c in chain]
    seen = {m.id for m in ordered}
    stmt = (
        select(ProviderModel, Provider)
        .join(Provider, Provider.id == ProviderModel.provider_id)
        .where(
            ProviderModel.enabled.is_(True),
            Provider.enabled.is_(True),
            ProviderModel.capabilities.overlap(sorted(PHASE_REQUIREMENTS[phase])),
        )
        .order_by(Provider.name, ProviderModel.model)
    )
    for m, p in (await session.execute(stmt)).all():
        if m.id not in seen:
            ordered.append(model_out(m, p))
    if project_id is not None:
        from opennotebook.providers.gateway import ModelGateway

        allowed = await ModelGateway(session).allowed_providers(project_id)
        if allowed is not None:
            ordered = [m for m in ordered if m.provider_id in allowed]
    return ordered
