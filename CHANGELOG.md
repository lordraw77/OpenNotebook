# Changelog

All notable changes. Images: `lordraw/opennotebook-{web,api,worker}` on Docker Hub.

## Unreleased (M6 — production readiness)

- Observability:
  - application metrics for HTTP, chat time to first token, retrieval, provider calls, ingestion, background
    tasks, queue depth and sources by status; the worker serves them on `:9101` (multiprocess);
  - optional OpenTelemetry tracing (FastAPI, httpx, Celery) to any OTLP endpoint;
  - `observability` profile with Prometheus (api + worker discovery, 7 alert rules), Grafana (provisioned
    *OpenNotebook overview* dashboard) and Jaeger;
  - the deployment Compose file inlines this configuration (`make sync-deploy`, checked in CI).
- Operations:
  - `scripts/backup.sh` / `scripts/restore.sh` (`make backup` / `make restore`), verified by restoring into a
    fresh stack;
  - `opennotebook reconcile [--fix]` (database / vectors / storage consistency);
  - `opennotebook rotate-encryption-key` (`APP_ENCRYPTION_KEY_PREVIOUS`);
  - SLOs, monitoring guide and runbooks in `docs/operations/`;
  - RAG evaluation set (`eval/`, `scripts/rag_eval.py`) and load test (`scripts/loadtest.py`) with baseline
    results.
- Hardening:
  - per-user rate limits on chat, deep research and search;
  - memory and PID limits per container;
  - OS security updates applied in the images;
  - `pip-audit`, `npm audit`, Trivy image scans and SPDX SBOM in CI (accepted exceptions documented).
- Release bundle: includes the deployment Compose file and the backup/restore scripts; `install.sh --yes`
  starts with `--pull never`. Verified on a host without the images.
- Fix: nginx re-resolves the api address, so recreating the api no longer causes 502 errors until the web
  container restarts.

## 0.5.1 — 2026-11-08

- Sources can be added to projects and workspaces, not only notebooks.

## 0.5.0 — 2026-11-08 (M5)

- Groups and sharing with groups.
- Single sign-on with OpenID Connect (Keycloak profile), group sync.
- Per-project provider policy.
- Zero-downtime embedding model change (atomic index switch).
- Deep research mode.
- `reset-admin` command.

## 0.4.0 — 2026-11-08 (M0–M4)

- Packaged stack with one command.
- Hierarchy with permissions and switches.
- Nine model providers with per-phase chains.
- Ingestion of documents, code, archives, images, scanned PDFs and web pages.
- Hybrid search and grounded chat with validated citations and a source viewer.
- Summaries, knowledge graph and wiki.
- Light and dark theme.
