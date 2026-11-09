# Runbooks

Commands run in the deployment directory (`docker-compose.yml` + `.env`). From a source checkout use
`docker compose --env-file .env -f deploy/compose/docker-compose.yml …` or the `make` targets.

## Alerts

### api down
`OpenNotebookApiDown` — the api does not answer Prometheus.
1. `docker compose ps api migrate` — if `migrate` exited with an error: `docker compose logs migrate`
   (wrong database password, failed migration), fix and `docker compose up -d`.
2. `docker compose logs --tail 200 api` — configuration errors are reported at start-up
   (`Missing required settings`).
3. `curl -s localhost:8080/api/health/ready` — shows which dependency (postgres, redis, qdrant, storage) fails.
4. Memory: `docker stats` — if the api hits `API_MEM_LIMIT` it is restarted; raise the limit.

### worker down
`OpenNotebookWorkerDown` — no worker exposes metrics. Uploads stay `queued`.
`docker compose ps worker`, `docker compose logs --tail 200 worker`, then `docker compose up -d worker`.
An out-of-memory kill (huge archive or image) shows as exit code 137: raise `WORKER_MEM_LIMIT` or lower
`UPLOAD_MAX_MB` / `ARCHIVE_MAX_UNCOMPRESSED_MB`.

### errors
`OpenNotebookHighErrorRate` — more than 5% of requests fail.
Dashboard panel *API requests by status* and `docker compose logs api | grep '"status": 5'` show the route.
Provider failures surface as 503 on search (`Embedding failed: …`): see *provider outage*.

### slow chat
`OpenNotebookChatSlow` — p95 time to first token above 8 s.
Panels *Provider latency p95* and *Retrieval p95* tell which part is slow. Provider: move a faster model first
in the chat chain (Settings → Models) or lower `CHAT_FIRST_TOKEN_TIMEOUT_S` so the fallback starts sooner.
Retrieval: check Qdrant (`docker stats qdrant`) and the rerank model (`RERANK_TIMEOUT_S`).

### provider outage
`OpenNotebookProviderErrors` — more than 25% of the calls to one provider fail.
1. Settings → Providers → **Test** on its models (expired key: HTTP 401; quota: 429; retired model: 404/410).
2. Chat and summaries fall back along their chains automatically; embeddings do not (one model per index):
   ingestion jobs retry with backoff up to `INGESTION_MAX_ATTEMPTS`, then the sources are `failed` —
   re-index them from RAG Status when the provider is back.
3. For a long outage of the embedding provider, change the embedding model of the affected projects and
   re-index: searches keep using the old index until the switch.

### queue backlog
`OpenNotebookQueueBacklog` — more than 100 jobs waiting for 30 minutes.
Panel *Queue depth* shows the queue. `parse`/`embed`: add workers (`docker compose up -d --scale worker=3`)
or speed up the embedding provider. `graph`/`summary`: slow LLM; use a faster model for those phases or
disable them (`GRAPH_ENABLED=false`, `SUMMARY_ENABLED=false`).

### ingestion failures
`OpenNotebookIngestionFailures` — RAG Status → *Failed sources* lists each error: unsupported or damaged files
are expected; provider errors resolve with the provider; others: `docker compose logs worker`.

## Routine procedures

### Back up
```bash
COMPOSE="docker compose" ./backup.sh -o /srv/backups        # scripts/backup.sh from the repository
```
Database (online dump), original files and vector index (their containers are paused for the copy), the env
file and a manifest with checksums. Keep backups off the host; they contain the provider keys (encrypted) and
`.env` (in clear). Schedule it with cron, e.g. `0 3 * * * cd /opt/opennotebook && ./backup.sh -o /srv/backups`.

### Restore
```bash
./restore.sh /srv/backups/opennotebook-<stamp>               # asks for confirmation; --yes to skip
```
Replaces all data, then starts the stack (migrations upgrade an older backup). The target `.env` must hold the
backup's `APP_ENCRYPTION_KEY` (copy it from `<backup>/env`). Verified: a backup restored into a fresh stack
serves the same sources, searches, files, entities and conversations.

### Check consistency
```bash
docker compose run --rm api reconcile          # report: vectors vs chunks, missing files, stuck jobs, orphans
docker compose run --rm api reconcile --fix    # re-queue inconsistent sources, delete orphan vectors
```
Run it after restoring an older vector index, after a crash, or when search misses a source that is `ready`.

### Rotate the encryption key
1. `openssl rand -base64 32` → new key.
2. In `.env`: `APP_ENCRYPTION_KEY_PREVIOUS=<old key>`, `APP_ENCRYPTION_KEY=<new key>`; `docker compose up -d`
   (the services read stored keys with either key meanwhile).
3. `docker compose run --rm api rotate-encryption-key` — re-encrypts every provider key; all or nothing.
4. Remove `APP_ENCRYPTION_KEY_PREVIOUS`, `docker compose up -d`, and update the key in your secret store and
   backups.

### Reset the administrator
`docker compose run --rm api reset-admin` (see [../deploy.md](../deploy.md#9-administrator-access)).

### Upgrade
Back up, set `VERSION`, `docker compose pull && docker compose up -d`; the migrate job runs first. If the
release notes change `docker-compose.yml`, download it again. Check `docker compose ps` and RAG Status.
