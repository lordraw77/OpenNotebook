"""Optional OpenTelemetry tracing (NFR-07).

Disabled unless OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. http://jaeger:4318 in the observability profile).
Traces cover HTTP requests (FastAPI), outgoing HTTP (httpx: model providers, Qdrant, web fetches) and Celery
tasks, plus database spans from SQLAlchemy cursor events (the upstream SQLAlchemy instrumentation does not
support SQLAlchemy 2.1). Span attributes never include request bodies, prompts, documents, SQL text or bound
parameters: a database span records only the operation and the first table (e.g. `SELECT sources`).
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

log = logging.getLogger(__name__)
_configured = False


_OPERATION = re.compile(r"^\s*(?:WITH\b.*?\)\s*)?(\w+)", re.IGNORECASE | re.DOTALL)
_TABLE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+(?:ONLY\s+)?\"?([A-Za-z_][\w.]*)\"?", re.IGNORECASE)
_SPANS_KEY = "otel_spans"


def statement_summary(statement: str) -> tuple[str, str | None]:
    """Operation and first table of a statement, without any literal or parameter."""
    match = _OPERATION.match(statement)
    operation = match.group(1).upper() if match else "SQL"
    if operation not in {"SELECT", "INSERT", "UPDATE", "DELETE", "WITH"}:
        return operation, None
    table = _TABLE.search(statement)
    return operation, table.group(1) if table else None


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]
    from opentelemetry import trace

    operation, table = statement_summary(statement)
    attributes: dict[str, Any] = {"db.system.name": "postgresql", "db.operation.name": operation}
    if table:
        attributes["db.collection.name"] = table
    if executemany:
        attributes["db.operation.batch.size"] = len(parameters) if hasattr(parameters, "__len__") else 0
    span = trace.get_tracer("opennotebook.db").start_span(
        f"{operation} {table}" if table else operation, kind=trace.SpanKind.CLIENT, attributes=attributes
    )
    conn.info.setdefault(_SPANS_KEY, []).append(span)


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany) -> None:  # type: ignore[no-untyped-def]
    spans = conn.info.get(_SPANS_KEY)
    if spans:
        spans.pop().end()


def _handle_error(exception_context) -> None:  # type: ignore[no-untyped-def]
    from opentelemetry.trace import Status, StatusCode

    conn = exception_context.connection
    spans = conn.info.get(_SPANS_KEY) if conn is not None else None
    if spans:
        span = spans.pop()
        error = exception_context.original_exception
        span.set_attribute("error.type", type(error).__name__)
        span.set_status(Status(StatusCode.ERROR))  # no message: it may echo parameter values
        span.end()


def instrument_database() -> None:
    """Records one client span per executed statement on every engine (sync and async)."""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    if not event.contains(Engine, "before_cursor_execute", _before_cursor_execute):
        event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
        event.listen(Engine, "after_cursor_execute", _after_cursor_execute)
        event.listen(Engine, "handle_error", _handle_error)


def configure_tracing(service: str, app=None) -> bool:  # type: ignore[no-untyped-def]
    global _configured
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    if not _configured:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        from opennotebook import __version__

        resource = Resource.create(
            {
                "service.name": os.environ.get("OTEL_SERVICE_NAME", f"opennotebook-{service}"),
                "service.version": __version__,
            }
        )
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        HTTPXClientInstrumentor().instrument()
        instrument_database()
        if service == "worker":
            from opentelemetry.instrumentation.celery import CeleryInstrumentor

            CeleryInstrumentor().instrument()
        _configured = True
        log.info(
            "OpenTelemetry tracing enabled", extra={"endpoint": os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]}
        )
    if app is not None:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health.*,metrics")
    return True
