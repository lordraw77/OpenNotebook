# Deployment Guide

Deploy OpenNotebook on a single Docker host from the published images, without the source tree.

Images (Docker Hub): [`lordraw/opennotebook-web`](https://hub.docker.com/r/lordraw/opennotebook-web),
[`lordraw/opennotebook-api`](https://hub.docker.com/r/lordraw/opennotebook-api),
[`lordraw/opennotebook-worker`](https://hub.docker.com/r/lordraw/opennotebook-worker). Tags: release versions
(e.g. `0.4.0`) and `latest`; `linux/amd64`.

## 1. Requirements

- Docker Engine with the Compose plugin **v2.23 or newer** (inline `configs` are used by the observability profile).
- 4 GB RAM (8 GB recommended), disk for the documents and the vector index.
- Outbound HTTPS from the host to the model providers you use (and to the web, if pages are added by URL).
- No GPU and no model download: every model runs at an external provider.

## 2. Files

```bash
mkdir -p /opt/opennotebook && cd /opt/opennotebook
BASE=https://raw.githubusercontent.com/lordraw77/OpenNotebook/HEAD
curl -fsSLO $BASE/deploy/production/docker-compose.yml
curl -fsSLO $BASE/.env.example
curl -fsSL  $BASE/scripts/gen-secrets.sh -o gen-secrets.sh && chmod +x gen-secrets.sh
```

`docker-compose.yml` needs nothing else from the repository; Compose reads `.env` from the same directory.

## 3. Configuration

```bash
./gen-secrets.sh .env   # copies .env.example and fills every empty internal secret (idempotent)
chmod 600 .env
$EDITOR .env
```

Set at least:

| Variable | Purpose |
|---|---|
| `BOOTSTRAP_ADMIN_EMAIL` | first administrator (password generated in `BOOTSTRAP_ADMIN_PASSWORD`) |
| `APP_PUBLIC_URL` | the URL users open, e.g. `https://notebook.example.com` |
| provider keys (`GEMINI_API_KEY`, `MISTRAL_API_KEY`, `GROQ_API_KEY`, …) | at least one chat and one embedding provider |
| `MODEL_CHAT`, `MODEL_EMBEDDING`, … (optional) | default model per phase, also editable in Settings → Models |
| `VERSION` | image version to run — pin it (e.g. `0.4.0`) |
| `WEB_BIND`, `WEB_PORT` | interface and port of the web UI (default `0.0.0.0:8080`) |

Rules: write comments on their own line (Compose does not strip inline comments), and keep
`APP_ENCRYPTION_KEY` safe — it decrypts the provider keys stored in the database.

### Single sign-on (optional)

OpenNotebook supports OpenID Connect (Authorization Code with PKCE) against any provider (Keycloak, Entra ID,
Google, Authentik, …). Settings in `.env`: `AUTH_MODE=both` (or `oidc` to disable passwords), `OIDC_ISSUER_URL`,
`OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`; register `<APP_PUBLIC_URL>/api/auth/oidc/callback` as redirect URI.
Accounts are created at the first sign-in (`OIDC_AUTO_CREATE_USERS`), linked to existing accounts by verified
email, and the `groups` claim is synchronized into OpenNotebook groups (`OIDC_ADMIN_GROUPS` grants the admin role).

With the bundled Keycloak (`--profile auth`): set `KEYCLOAK_BIND=0.0.0.0`,
`KEYCLOAK_PUBLIC_URL=http://<host>:8081` (the URL browsers use; it becomes the token issuer) and
`OIDC_ISSUER_URL=http://keycloak:8081/realms/<realm>` (the api reaches Keycloak on the internal network). In the
realm, create a confidential client with the redirect URI above and a "Group Membership" mapper (claim `groups`,
full path off, added to the ID token).

## 4. Start

```bash
docker compose pull
docker compose up -d
docker compose ps          # all services healthy; `migrate` exited 0
docker compose logs migrate
```

Open `http://<host>:8080`, sign in with the bootstrap administrator, then:

1. **Settings → Providers**: providers imported from `.env`; enable models and use **Test**.
2. **Settings → Models**: chains per phase (chat, embedding, summary, graph extraction, vision, OCR, rerank),
   globally or per project.
3. **Workbench**: create a project, upload sources, ask questions; **Wiki** for the knowledge graph.

Optional profiles: `docker compose --profile observability up -d` (Prometheus on `127.0.0.1:9090`, Grafana on
`127.0.0.1:3000`), `--profile auth` (Keycloak on `127.0.0.1:8081`), or `COMPOSE_PROFILES=…` in `.env`.

## 5. TLS and reverse proxy

The web container speaks plain HTTP on port 8080. In production, bind it to localhost
(`WEB_BIND=127.0.0.1`) and terminate TLS in a reverse proxy (Caddy, Traefik, nginx) on the same host. Requirements
for the proxy:

- disable response buffering for `/api/` (the chat is a server-sent event stream) and allow long reads (≥ 600 s);
- allow request bodies up to `UPLOAD_MAX_MB`;
- forward `X-Forwarded-Proto` / `X-Forwarded-For`.

Example (Caddy): `notebook.example.com { reverse_proxy 127.0.0.1:8080 { flush_interval -1 } }`.

## 6. Upgrade

```bash
# set the new VERSION in .env, and fetch the matching compose file if the release notes say so
docker compose pull
docker compose up -d       # the migrate job applies database migrations before api/worker start
```

All three OpenNotebook images must run the same version. Migrations are backward compatible within a release
line; take a backup before upgrading.

## 7. Backup and restore

| Data | How |
|---|---|
| PostgreSQL (`pg-data`) | `docker compose exec -T postgres pg_dump -U opennotebook opennotebook \| gzip > db.sql.gz` |
| Files (`blob-data`) | stop the stack or snapshot the volume; e.g. `docker run --rm -v opennotebook_blob-data:/d -v $PWD:/b alpine tar czf /b/blobs.tgz -C /d .` |
| `APP_ENCRYPTION_KEY` (and the whole `.env`) | store in your secret manager |
| Vector index (`qdrant-data`) | optional: rebuildable with **RAG Status → Re-index** (costs embedding calls) |

## 8. Operations

- Scale ingestion: `docker compose up -d --scale worker=3`.
- Logs: JSON on stdout, rotated by Docker (20 MB × 5 per container); `docker compose logs -f api worker`.
- Health: `docker compose ps`; the **RAG Status** page shows queues, failed sources and recent jobs.
- Troubleshooting table: [docker.md](docker.md#troubleshooting).

## 9. Administrator access

Lost the administrator password, or need an administrator on an SSO-only instance:

```bash
# uses BOOTSTRAP_ADMIN_EMAIL / BOOTSTRAP_ADMIN_PASSWORD from .env (edit them first), or --email / RESET_ADMIN_PASSWORD
docker compose run --rm api reset-admin
```

It creates the account or resets its password, admin role and active state, and revokes its sessions.
Password sign-in must be enabled (`AUTH_MODE=local` or `both`) to use it.

## 10. Without registry access

Build a self-contained bundle on a machine with the source tree: `make bundle` produces
`dist/opennotebook-<version>-bundle.tar.gz` (images + compose files + `.env.example` + `install.sh`).
