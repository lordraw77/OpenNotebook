"""Liveness, readiness and component status."""

from __future__ import annotations

import asyncio
import time

import httpx
from fastapi import APIRouter, Response, status
from sqlalchemy import text

from opennotebook import __version__
from opennotebook.config import get_settings
from opennotebook.db import get_engine
from opennotebook.deps import CurrentUser
from opennotebook.storage import get_blob_store

router = APIRouter(prefix="/api/health", tags=["health"])


async def _timed(name: str, coro) -> dict:  # type: ignore[no-untyped-def]
    start = time.perf_counter()
    try:
        await asyncio.wait_for(coro, timeout=5)
        return {"name": name, "ok": True, "latency_ms": int((time.perf_counter() - start) * 1000)}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "ok": False, "error": exc.__class__.__name__}


async def _db() -> None:
    async with get_engine().connect() as conn:
        await conn.execute(text("SELECT 1"))


async def _redis() -> None:
    from redis.asyncio import from_url

    client = from_url(get_settings().redis_url_with_auth)
    try:
        await client.ping()
    finally:
        await client.aclose()


async def _qdrant() -> None:
    settings = get_settings()
    headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{settings.qdrant_url.rstrip('/')}/readyz", headers=headers)
        resp.raise_for_status()


async def _storage() -> None:
    await get_blob_store().check()


async def check_components() -> list[dict]:
    return list(
        await asyncio.gather(
            _timed("postgres", _db()),
            _timed("redis", _redis()),
            _timed("qdrant", _qdrant()),
            _timed("storage", _storage()),
        )
    )


@router.get("/live")
async def live() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/ready")
async def ready(response: Response) -> dict:
    components = await check_components()
    ok = all(c["ok"] for c in components)
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "components": components}


@router.get("/status")
async def component_status(_: CurrentUser) -> dict:
    """Detailed status for the RAG Status page (authenticated)."""
    components = await check_components()
    return {"version": __version__, "components": components}
