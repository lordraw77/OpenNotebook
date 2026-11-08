"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from opennotebook import __version__
from opennotebook.api import (
    assignments,
    auth,
    conversations,
    health,
    ingestion_status,
    nodes,
    notes,
    providers,
    sources,
    users,
)
from opennotebook.config import get_settings
from opennotebook.logging_setup import configure_logging

log = logging.getLogger("opennotebook.http")

REQUESTS = Counter("opennotebook_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("opennotebook_http_request_duration_seconds", "HTTP request latency", ["method", "route"])


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    if settings.app_env != "test":
        settings.validate_for_runtime()

    app = FastAPI(
        title="OpenNotebook API",
        version=__version__,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start
        route = request.scope.get("route")
        route_path = getattr(route, "path", "unmatched")
        REQUESTS.labels(request.method, route_path, response.status_code).inc()
        LATENCY.labels(request.method, route_path).observe(elapsed)
        response.headers["x-request-id"] = request_id
        if not route_path.startswith("/api/health"):
            log.info(
                "request",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": route_path,
                    "status": response.status_code,
                    "duration_ms": int(elapsed * 1000),
                },
            )
        return response

    for router in (
        health.router,
        auth.router,
        users.router,
        nodes.router,
        providers.router,
        assignments.router,
        sources.router,
        notes.router,
        ingestion_status.router,
        conversations.router,
    ):
        app.include_router(router)

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return app


app = create_app()
