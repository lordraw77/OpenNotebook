"""Knowledge graph and wiki: entities, relations and generated pages, always limited to visible sources."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from opennotebook.acl import get_search_scope
from opennotebook.chat.service import context_entry
from opennotebook.deps import CurrentUser, SessionDep
from opennotebook.graph.query import entity_detail, graph_view, list_entities
from opennotebook.graph.wiki import wiki_page
from opennotebook.ingestion.search import SearchHit
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
