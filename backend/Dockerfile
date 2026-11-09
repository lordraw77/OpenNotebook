# OpenNotebook backend images: `api` (default) and `worker` targets.
# No model weights or ML runtimes are installed (checked by scripts/check-no-models.sh).

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

FROM ${PYTHON_IMAGE} AS base
# Security updates of the Debian base (e.g. zlib) published after the base image was built.
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LITELLM_LOCAL_MODEL_COST_MAP=True \
    LITELLM_TELEMETRY=False

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM base AS api
ARG VERSION=dev
LABEL org.opencontainers.image.title="OpenNotebook API" \
      org.opencontainers.image.description="OpenNotebook REST/SSE API (FastAPI): grounded RAG chat, knowledge graph, model gateway. No models inside." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/lordraw77/OpenNotebook" \
      org.opencontainers.image.url="https://hub.docker.com/r/lordraw/opennotebook-api"
RUN useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=build --chown=root:root /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH
USER 10001
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/live', timeout=4)"]
ENTRYPOINT ["opennotebook"]
CMD ["api"]

FROM api AS worker
# Same code and dependencies as the api (parsers, tree-sitter grammars, trafilatura, Pillow are Python wheels);
# only the entrypoint and health check differ.
LABEL org.opencontainers.image.title="OpenNotebook worker" \
      org.opencontainers.image.description="OpenNotebook ingestion worker (Celery): parsing, OCR/vision calls, web fetching, embeddings, knowledge graph, summaries. No models inside." \
      org.opencontainers.image.url="https://hub.docker.com/r/lordraw/opennotebook-worker"
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=3 \
  CMD ["sh", "-c", "celery -A opennotebook.worker:celery_app inspect ping -d celery@$HOSTNAME --timeout 10 >/dev/null"]
CMD ["worker"]
