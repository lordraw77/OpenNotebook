# OpenNotebook converter: office documents to PDF with headless LibreOffice (no models, no network access needed).
# Runs on an internal-only network reachable by the worker alone (threat T5).

ARG PYTHON_IMAGE=python:3.12.16-slim-trixie
FROM ${PYTHON_IMAGE}
ARG VERSION=dev
LABEL org.opencontainers.image.title="OpenNotebook converter" \
      org.opencontainers.image.description="Isolated office-to-PDF converter (headless LibreOffice) for OpenNotebook ingestion." \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.source="https://github.com/lordraw77/OpenNotebook" \
      org.opencontainers.image.url="https://hub.docker.com/r/lordraw/opennotebook-converter"
# Metric-compatible fonts (Carlito = Calibri, Caladea = Cambria, Liberation = Arial/Times/Courier) keep the page
# breaks close to the original, so page anchors match what users see in Office.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends \
        libreoffice-writer-nogui libreoffice-calc-nogui libreoffice-impress-nogui \
        fonts-liberation fonts-dejavu-core fonts-crosextra-carlito fonts-crosextra-caladea \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10002 --user-group --no-create-home --shell /usr/sbin/nologin converter
COPY server.py /app/server.py
USER 10002
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)"]
ENTRYPOINT ["python", "/app/server.py"]
