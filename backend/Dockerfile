# OpenNotebook backend images: `api` (default) and `worker` targets.
# No model weights or ML runtimes are installed (checked by scripts/check-no-models.sh).

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie

FROM ${PYTHON_IMAGE} AS base
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
# From M1 this stage adds LibreOffice (DOCX/PPTX -> PDF), tree-sitter grammars and Playwright Chromium.
HEALTHCHECK --interval=30s --timeout=15s --start-period=30s --retries=3 \
  CMD ["sh", "-c", "celery -A opennotebook.worker:celery_app inspect ping -d celery@$HOSTNAME --timeout 10 >/dev/null"]
CMD ["worker"]
