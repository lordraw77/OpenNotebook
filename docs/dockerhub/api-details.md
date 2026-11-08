## About this image

- Entry point `opennotebook`; commands: `api` (default, port **8000**), `migrate`, `bootstrap`, `worker`.
- Python 3.12 on Debian slim; dependencies installed from a hash-locked `uv.lock`; LiteLLM pinned to an exact
  version.
- Health checks: `GET /api/health/live` (process) and `GET /api/health/ready` (PostgreSQL, Redis, Qdrant,
  storage); Prometheus metrics on `/metrics` (internal network only).
- Configuration: environment variables from `.env` — see `.env.example` in the repository for every setting
  (database, Qdrant, Redis, S3 storage, provider keys, `MODEL_*` defaults, chat, ingestion and graph limits).
