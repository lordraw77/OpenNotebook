# Docker Overview

OpenNotebook is distributed **only as container images**, started from **one Compose file**:
`deploy/compose/docker-compose.yml`. The stack contains application services and infrastructure only;
**no model runs inside it**. Every model call goes to an external provider (Groq, OpenRouter, Gemini, Cloudflare,
Cerebras, Mistral, NVIDIA, Hugging Face, or an existing Ollama server).

Always run Compose from the repository root with the env file, or use the Makefile, which does it for you:

```bash
docker compose --env-file .env -f deploy/compose/docker-compose.yml up -d
make up
```

## Images

All OpenNotebook images share the release version (`VERSION` file / `VERSION` variable) and the `REGISTRY` prefix.

| Image | Built from | Purpose | Size (M0) |
|---|---|---|---|
| `opennotebook/web` | `frontend/` | Angular SPA served by unprivileged nginx; proxies `/api` to the api service (unbuffered, for the chat event stream); security headers; serves the pdf.js worker from `/pdfjs/` | ~70 MB |
| `opennotebook/api` | `backend/` (target `api`) | FastAPI REST + SSE API; also runs the `migrate` one-shot job | ~520 MB |
| `opennotebook/worker` | `backend/` (target `worker`) | Celery ingestion worker (LibreOffice, tree-sitter, Playwright are added in M1/M3) | ~520 MB |

Third-party images: `postgres:18.6-alpine`, `qdrant/qdrant:v1.20.0`, `chrislusf/seaweedfs:4.52`, `redis:8.8.4-alpine`,
and in profiles `quay.io/keycloak/keycloak:26.8.1`, `prom/prometheus:v3.15.1`, `grafana/grafana:13.2.5`.
Tags are pinned; digests are pinned at release time.

OpenNotebook images run as a non-root user with a read-only root filesystem, `no-new-privileges` and all capabilities
dropped; they have a `HEALTHCHECK`, log JSON to stdout, and contain no model weights or ML runtimes (`make check-no-models`).

## Services

| Service | Port | Depends on | Health check |
|---|---|---|---|
| `web` | host `${WEB_BIND}:${WEB_PORT}` → 8080 | api (healthy) | `GET /healthz` |
| `api` | internal 8000 | migrate (completed), redis, qdrant | `GET /api/health/live`; `/api/health/ready` checks all dependencies |
| `worker` | — | migrate (completed), redis | Celery `inspect ping` |
| `migrate` | — (one-shot) | postgres, seaweedfs | exits 0 after `opennotebook migrate && opennotebook bootstrap` |
| `postgres` | internal 5432 | — | `pg_isready` |
| `qdrant` | internal 6333 | — | TCP check (API key required for requests) |
| `seaweedfs` | internal 8333 (S3) | — | master `/cluster/status` + S3 `/status` |
| `redis` | internal 6379 | — | `PING` with password |

Networks: `internal` (no internet access) for databases and storage; `egress` for api/worker, which call the providers;
`public` for published ports. Only `web` is published by default.

### First start (`migrate` job)

`opennotebook bootstrap` is idempotent and runs after every migration:

1. creates the storage bucket;
2. creates the first administrator from `BOOTSTRAP_ADMIN_EMAIL` / `BOOTSTRAP_ADMIN_PASSWORD` if no user exists;
3. registers a provider for every key present in `.env` (`GROQ_API_KEY`, …, `OLLAMA_API_BASE`) that is not registered yet;
4. syncs the model catalog of providers never synced (a failing provider is reported and skipped);
5. applies `MODEL_<PHASE>` defaults when the global chain of that phase is empty.

The report is in `docker compose logs migrate`. Re-run it with `make bootstrap`.

## One Compose file, optional profiles

Compose **profiles** let one file describe both the core stack and optional add-ons, instead of several files.

- A service **without** a `profiles:` key always starts.
- A service **with** `profiles: [name]` starts only when that profile is enabled.

```yaml
services:
  api:                       # no profiles key -> always started
    image: ${REGISTRY:-opennotebook}/api:${VERSION:-dev}
  keycloak:
    profiles: [auth]         # started only with the "auth" profile
  prometheus:
    profiles: [observability]
```

Enable profiles on the command line or in `.env`:

```bash
docker compose --env-file .env -f deploy/compose/docker-compose.yml up -d                           # core only
docker compose --env-file .env -f deploy/compose/docker-compose.yml --profile observability up -d   # + observability
# or set COMPOSE_PROFILES=auth,observability in .env and run `make up`
```

| Profile | Adds | Use when |
|---|---|---|
| *(none)* | web, api, worker, migrate, postgres, qdrant, seaweedfs, redis | always: a complete, working instance |
| `auth` | Keycloak on `127.0.0.1:8081` | OIDC single sign-on (application integration in M5) |
| `observability` | Prometheus on `127.0.0.1:9090` (scrapes `api:8000/metrics`), Grafana on `127.0.0.1:3000` | metrics dashboards; OTel traces and Loki logs arrive in M6 |

There is no model-serving profile. Ollama, if used, is your existing external server, set with `OLLAMA_API_BASE`.

## Volumes

| Volume | Content | Back up |
|---|---|---|
| `pg-data` | PostgreSQL (source of truth, including encrypted provider keys) | **yes** |
| `blob-data` | SeaweedFS data (original files, snapshots) | **yes** |
| `qdrant-data` | vector index (rebuildable by re-embedding through the provider) | recommended: rebuilding costs provider calls |
| `redis-data` | queues | no |
| `keycloak-data`, `prometheus-data`, `grafana-data` | profile services | optional |

Also back up `APP_ENCRYPTION_KEY`: without it the stored provider keys cannot be decrypted.

## Configuration

`make secrets` creates `.env` from `.env.example` (if missing) and fills every **empty** internal secret:
`APP_SECRET_KEY`, `APP_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `QDRANT_API_KEY`, `REDIS_PASSWORD`, `S3_ACCESS_KEY`,
`S3_SECRET_KEY`, `BOOTSTRAP_ADMIN_PASSWORD`, `KEYCLOAK_ADMIN_PASSWORD`, `GRAFANA_ADMIN_PASSWORD`. Existing values,
including provider keys, are never changed.

Then add at least one chat and one embedding provider key. Provider keys in `.env` are imported into the encrypted
registry at first start; afterwards manage them in **Settings → Providers**.

> **Write comments on their own line in `.env`.** Docker Compose does not strip inline comments:
> `COMPOSE_PROFILES=   # note` sets the variable to the text of the note.

External Ollama: set `OLLAMA_API_BASE=http://<host>:11434`; the host must be reachable from the `egress` network.
For a slow CPU-only server raise `OLLAMA_TIMEOUT_S`.

Chat tuning (`CHAT_*`, `RERANK_TIMEOUT_S`): how many passages are retrieved and given to the model, the history
length, the answer length and the interactive timeouts; defaults are in `.env.example`.

## Make targets

| Target | Action |
|---|---|
| `make help` | list targets |
| `make secrets` | create `.env` and generate missing internal secrets |
| `make build` (`docker/build`) | build web, api and worker images |
| `make up` (`run`, `docker/run`) / `make down` (`docker/stop`) | start / stop the stack (profiles from `COMPOSE_PROFILES`) |
| `make restart` | restart api, worker and web |
| `make logs` / `make ps` | follow logs / service status and health |
| `make migrate` / `make bootstrap` | run migrations / re-run first-start initialization |
| `make doctor` | check connectivity to every internal service and every configured provider |
| `make test` (`test/backend`, `test/frontend`) | test suites (backend uses disposable PostgreSQL + Redis containers) |
| `make lint` / `make fmt` | ruff + prettier |
| `make check-no-models` | verify images contain no ML runtimes or model weights |
| `make bundle` | release tarball: images + compose + `.env.example` + `install.sh` |
| `make release VERSION=x.y.z REGISTRY=…` | build, check and push images |
| `make clean` | stop and **delete all volumes** (asks for confirmation) |

Use another env file with `ENV_FILE=path`, e.g. `make up ENV_FILE=.env.staging`.

## Install from a release bundle

For hosts that cannot pull from the registry (providers must still be reachable):

```bash
make bundle                                   # on a machine that can build or pull the images
# copy dist/opennotebook-<version>-bundle.tar.gz to the target host
tar xzf opennotebook-<version>-bundle.tar.gz && cd opennotebook-<version>
./install.sh                                  # docker load, create .env, then compose up
```

## Operations

- **Startup order**: postgres + seaweedfs → migrate → api/worker → web (Compose `depends_on` with health conditions).
- **Restart policy**: `unless-stopped` for long-running services.
- **Scaling workers**: `docker compose … up -d --scale worker=3`; workers are I/O-bound (provider calls), so throughput is limited by provider rate limits more than by CPU.
- **Upgrade**: pull or build the new version, `make up`; migrations are backward compatible (expand → migrate → contract).
- **Backup**: `pg_dump` of the database + copy of `blob-data` + `APP_ENCRYPTION_KEY`.
- **Debug**: `make logs`, `make doctor`, `GET /api/health/ready` (inside the network) or **RAG Status** in the UI.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `migrate` exits 1 | `docker compose … logs migrate`; usually a wrong `POSTGRES_PASSWORD` after the volume was created with another one |
| A provider shows "error" after sync | invalid or expired key (e.g. HTTP 401), or the provider is unreachable; fix the key in Settings → Providers and sync again |
| Model test returns 404/410 | the provider still lists a retired model; it is marked unavailable automatically |
| `RateLimitError` / "payment required" | account limits of the provider; add fallback models to the chain |
| Blank/black page, components unstyled | an inline script was blocked by the CSP; the production build must keep `inlineCritical: false` (frontend/angular.json) so no inline script is emitted |
| Chat answer shows "All chat models in the chain failed" | every model of the chat chain failed before answering (rate limit, expired key, timeout): the error lists each attempt; add a fallback model in Settings → Models or pick another model in the Workbench |
| Chat waits a long time before answering | a slow chat model (e.g. CPU-only Ollama) gets `CHAT_FIRST_TOKEN_TIMEOUT_S` to start; lower it to fall back sooner |
| PDF viewer stays empty, console reports a module MIME type error | the `/pdfjs/` location of `frontend/nginx.conf` (serves `.mjs` as JavaScript) is missing from a custom nginx config |
| Sources stay in `embedding`, search returns 503 "Timeout" | the embedding provider is slow or saturated (e.g. a CPU-only Ollama also serving chat models); check **RAG Status → Recent jobs**, or assign a faster embedding model globally or per project and re-index |
| Unexpected profile services start | inline comment in `.env` on `COMPOSE_PROFILES` (see Configuration) |
