"""Optional OpenTelemetry tracing (NFR-07).

Disabled unless OTEL_EXPORTER_OTLP_ENDPOINT is set (e.g. http://jaeger:4318 in the observability profile).
Traces cover HTTP requests (FastAPI), outgoing HTTP (httpx: model providers, Qdrant, web fetches) and Celery
tasks. Database spans are not recorded yet: the SQLAlchemy instrumentation does not support SQLAlchemy 2.1.
Span attributes never include request bodies, prompts or documents.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)
_configured = False


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
