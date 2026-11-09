"""Knowledge graph and wiki: entities, relations and generated pages, always limited to visible sources."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from opennotebook.acl import get_node_for, get_search_scope
from opennotebook.chat.service import context_entry
from opennotebook.deps import CurrentUser, SessionDep
from opennotebook.graph import edit
from opennotebook.graph.query import entity_detail, graph_view, list_entities
from opennotebook.graph.wiki import wiki_page
from opennotebook.ingestion.search import SearchHit
from opennotebook.models import Entity, GrantRole, Relation
from opennotebook.providers.gateway import GatewayError

router = APIRouter(prefix="/api", tags=["graph"])


class EntityOut(BaseModel):
    id: uuid.UUID
    name: str
    type: str
    mentions: int
    sources: int


class GraphOut(BaseModel):
    nodes: list[EntityOut]
    edges: list[dict]


@router.get("/entities", response_model=list[EntityOut])
async def entities(
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
    q: str | None = Query(default=None, max_length=200),
    type: list[str] | None = Query(default=None),  # noqa: A002 - query parameter name
    limit: int = Query(default=100, ge=1, le=500),
) -> list[EntityOut]:
    scope = await get_search_scope(session, user, scope_id)
    rows = await list_entities(session, user, scope, query=q, types=type, limit=limit)
    return [EntityOut(**r.__dict__) for r in rows]


@router.get("/graph", response_model=GraphOut)
async def graph(
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
    limit: int = Query(default=150, ge=1, le=500),
) -> GraphOut:
    scope = await get_search_scope(session, user, scope_id)
    nodes, edges = await graph_view(session, user, scope, limit)
    return GraphOut(nodes=[EntityOut(**n.__dict__) for n in nodes], edges=edges)


async def _detail(session: SessionDep, user: CurrentUser, scope_id: uuid.UUID, entity_id: uuid.UUID) -> dict:
    scope = await get_search_scope(session, user, scope_id)
    detail = await entity_detail(session, user, scope, entity_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    detail["_scope"] = scope
    return detail


@router.get("/entities/{entity_id}")
async def entity(
    entity_id: uuid.UUID, user: CurrentUser, session: SessionDep, scope_id: uuid.UUID = Query()
) -> dict:
    detail = await _detail(session, user, scope_id, entity_id)
    mentions = detail.pop("mentions")
    detail.pop("_scope")
    detail["mention_count"] = len(mentions)
    detail["mentions"] = [
        {
            **context_entry(
                i + 1, SearchHit(chunk=m["chunk"], source=m["source"], notebook=m["notebook"], score=0)
            ),
            "description": m["description"],
        }
        for i, m in enumerate(mentions[:50])
    ]
    return detail


@router.post("/entities/{entity_id}/wiki")
async def entity_wiki(
    entity_id: uuid.UUID,
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
    refresh: bool = False,
) -> dict:
    """Wiki page from the passages this user can see (generated on first request, then cached)."""
    detail = await _detail(session, user, scope_id, entity_id)
    scope = detail.pop("_scope")
    try:
        return await wiki_page(session, user, scope, detail, refresh=refresh)
    except GatewayError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, f"Wiki generation failed: {exc.describe()}"
        ) from exc


# --- graph editor -----------------------------------------------------------------------
# Edits change the project graph for everyone, so they need the editor role on the project itself; the
# entity must also be visible to the caller in the scope they send (an invisible one answers as missing).


async def _editable(
    session: SessionDep, user: CurrentUser, scope_id: uuid.UUID, entity_id: uuid.UUID
) -> Entity:
    await _detail(session, user, scope_id, entity_id)  # 404 unless visible
    entity = await session.get(Entity, entity_id)
    if entity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    await get_node_for(session, user, entity.project_id, GrantRole.editor)
    return entity


def _invalid(exc: edit.EditError) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


class EntityPatch(BaseModel):
    name: str | None = Field(default=None, max_length=300)
    type: str | None = Field(default=None, max_length=40)


class MergeBody(BaseModel):
    target_id: uuid.UUID


class RelationBody(BaseModel):
    scope_id: uuid.UUID
    source_id: uuid.UUID
    target_id: uuid.UUID
    type: str = Field(min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=1000)


@router.patch("/entities/{entity_id}")
async def patch_entity(
    entity_id: uuid.UUID,
    body: EntityPatch,
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
) -> dict:
    entity = await _editable(session, user, scope_id, entity_id)
    try:
        await edit.edit_entity(session, entity, body.name, body.type)
    except edit.EditError as exc:
        raise _invalid(exc) from exc
    await session.commit()
    return await entity_detail_out(session, user, scope_id, entity_id)


@router.post("/entities/{entity_id}/merge")
async def merge_entity(
    entity_id: uuid.UUID,
    body: MergeBody,
    user: CurrentUser,
    session: SessionDep,
    scope_id: uuid.UUID = Query(),
) -> dict:
    """Merge this entity into `target_id` (both visible): the target keeps its name and gains the rest."""
    entity = await _editable(session, user, scope_id, entity_id)
    target = await _editable(session, user, scope_id, body.target_id)
    shown = (await _detail(session, user, scope_id, body.target_id))["name"]
    try:
        await edit.merge_entities(session, entity, target, shown)
    except edit.EditError as exc:
        raise _invalid(exc) from exc
    await session.commit()
    return await entity_detail_out(session, user, scope_id, target.id)


@router.delete("/entities/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entity(
    entity_id: uuid.UUID, user: CurrentUser, session: SessionDep, scope_id: uuid.UUID = Query()
) -> None:
    entity = await _editable(session, user, scope_id, entity_id)
    await edit.delete_entity(session, entity)
    await session.commit()


@router.post("/relations", status_code=status.HTTP_201_CREATED)
async def add_relation(body: RelationBody, user: CurrentUser, session: SessionDep) -> dict:
    src = await _editable(session, user, body.scope_id, body.source_id)
    dst = await _editable(session, user, body.scope_id, body.target_id)
    try:
        relation = await edit.add_relation(session, src, dst, body.type, body.description)
    except edit.EditError as exc:
        raise _invalid(exc) from exc
    await session.commit()
    return {"id": str(relation.id), "type": relation.type}


@router.delete("/relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_relation(
    relation_id: uuid.UUID, user: CurrentUser, session: SessionDep, scope_id: uuid.UUID = Query()
) -> None:
    relation = await session.get(Relation, relation_id)
    if relation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Relation not found")
    await _editable(session, user, scope_id, relation.src_id)  # visible through one of its ends
    await edit.delete_relation(session, relation)
    await session.commit()


async def entity_detail_out(
    session: SessionDep, user: CurrentUser, scope_id: uuid.UUID, entity_id: uuid.UUID
) -> dict:
    return await entity(entity_id, user, session, scope_id)
