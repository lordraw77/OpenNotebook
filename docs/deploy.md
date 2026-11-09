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

### Git repositories (optional)

Repositories (for example an intranet GitLab over plain HTTP) can be added as sources in **Upload → Add a git
repository**. They are off until the operator lists the hosts that may be cloned:

```bash
# .env: hosts (with the port when it is not the default), comma-separated
GIT_ALLOWED_HOSTS=gitlab.lan,git.example.com:8080
```

The worker clones the branch, indexes each file as a child source and, with a schedule, syncs again (the worker
checks every minute which repositories are due; `GIT_SYNC_SCHEDULER=false` turns the schedule off). A sync asks
the server for the branch's commit first: if nothing changed nothing is cloned; otherwise only added, changed and
removed files are processed. The worker host must reach the Git server (a LAN address works: the worker is on the
egress network). For private repositories create a GitLab access token with `read_repository` and paste it in the
form; it is stored encrypted and never shown again. Use the exact clone URL: redirects are not followed.

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
`127.0.0.1:3000`), `--profile auth` (Keycloak on `127.0.0.1:8081`), `--profile converter` (office documents to
PDF; also set `CONVERTER_URL=http://converter:8080`), or `COMPOSE_PROFILES=…` in `.env`.

### Kubernetes (Helm)

`deploy/helm/opennotebook` installs the same stack on Kubernetes: web, api, worker, a migration Job (`migrate` +
`bootstrap` at every install or upgrade, with `wait-migrations` init containers on the api and worker),
optional converter, and single-replica PostgreSQL, Qdrant, SeaweedFS and Redis StatefulSets.

```bash
helm install on deploy/helm/opennotebook -n opennotebook --create-namespace \
  --set config.APP_PUBLIC_URL=https://notes.example.com --set ingress.enabled=true --set ingress.host=notes.example.com \
  --set providerKeys.GROQ_API_KEY=... --set providerKeys.MISTRAL_API_KEY=...
kubectl get secret on-opennotebook-secrets -n opennotebook -o jsonpath='{.data.BOOTSTRAP_ADMIN_PASSWORD}' | base64 -d
```

- Secrets are generated at first install and kept across upgrades and `helm uninstall` (`resource-policy: keep`,
  they protect the data); or pass `existingSecret` (keys of `values.yaml`). Back up the Secret with the database.
- For production use managed data services: `postgresql.enabled=false` and `external.postgresql.*`, likewise
  `qdrant`, `redis`, `seaweedfs` (any S3 store, `external.s3.*`).
- NetworkPolicies mirror the Compose networks: data services accept the api, worker and migration pods only; the
  converter accepts the worker only and has no egress. They need a CNI that enforces them.
- Ingress: the chat is an event stream; disable proxy buffering and allow long reads and 500 MB bodies (annotations
  in `values.yaml`). Pods run non-root with a read-only root filesystem and no capabilities.
- Validated in CI with `helm lint` and kubeconform (Kubernetes 1.33). It has not been installed on a live
  cluster yet: try it on a test cluster first.

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

Download the scripts once (they are also in the release bundle):

```bash
curl -fsSLO $BASE/scripts/backup.sh && curl -fsSLO $BASE/scripts/restore.sh && chmod +x backup.sh restore.sh
./backup.sh -o /srv/backups            # database, original files, vector index, .env + manifest with checksums
./restore.sh /srv/backups/opennotebook-<stamp>     # replaces all data (asks for confirmation)
```

The database is dumped online; SeaweedFS and Qdrant are paused for the seconds their volumes are copied.
Backups contain `.env` in clear (secrets): store them encrypted and off the host. Restoring into a new host
works as long as the target `.env` holds the backup's `APP_ENCRYPTION_KEY`. Details, scheduling and the
consistency check (`reconcile`): [operations/runbooks.md](operations/runbooks.md#routine-procedures).

## 8. Operations

Monitoring (metrics, dashboard, alerts, traces): [operations/monitoring.md](operations/monitoring.md).
SLOs: [operations/slo.md](operations/slo.md). Incident runbooks: [operations/runbooks.md](operations/runbooks.md).


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
