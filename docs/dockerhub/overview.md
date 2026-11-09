# OpenNotebook — {{TITLE}}

**Self-hosted knowledge workspace with grounded RAG chat and traceable citations.**
Upload documents, source code, archives, images, web pages and notes; organize them in a freely nested
**Project → Workspace → Notebook** tree; chat with an LLM that answers **only** from the sources in the selected
scope, with every statement linked to the exact passage it comes from.

{{ROLE}}

> This image is one of the three OpenNotebook application images. Run them together with the Compose file
> described below — they are not meant to be started alone.

| Image | Role |
|---|---|
| [`lordraw/opennotebook-web`](https://hub.docker.com/r/lordraw/opennotebook-web) | Web UI (Angular) on unprivileged nginx; proxies `/api` to the api |
| [`lordraw/opennotebook-api`](https://hub.docker.com/r/lordraw/opennotebook-api) | REST + streaming API (FastAPI); also runs the one-shot `migrate` job |
| [`lordraw/opennotebook-worker`](https://hub.docker.com/r/lordraw/opennotebook-worker) | Ingestion worker (Celery): parsing, OCR, web fetching, embeddings, knowledge graph, summaries |
| [`lordraw/opennotebook-converter`](https://hub.docker.com/r/lordraw/opennotebook-converter) | Optional isolated document converter (headless LibreOffice): office files to PDF |

## No models inside

The images contain **no model weights, no inference server and no ML runtime**. Every model call (chat,
summaries, knowledge-graph extraction, image description, OCR, embeddings, rerank) goes to an external provider
you configure: **Groq, OpenRouter, Google Gemini, Cloudflare Workers AI, Cerebras, Mistral, NVIDIA NIM,
Hugging Face**, or your own **Ollama** server. Each phase has its own model chain with fallbacks, globally or per
project. A working instance needs one chat model and one embedding model (Gemini or Mistral alone covers both).

## Features

- **Ingestion**: PDF (scanned pages via OCR), DOCX, Markdown, text, HTML; source code with structure-aware
  chunking (tree-sitter: C, C++, Python, JS/TS, Java, Go, Rust, C#, PHP, Ruby, shell); ZIP/TAR archives (every file
  becomes a source; zip-bomb and path-traversal protection); images (OCR + description); web pages by URL with an
  optional same-site crawl (SSRF-protected); notes.
- **Search**: hybrid dense + BM25 retrieval with the access-control and on/off-switch filters applied *inside*
  the query; optional external rerank.
- **Grounded chat**: streaming answers, strict prompt, validated `[S1]` citations that open the source at the
  cited passage (PDF page with the passage highlighted, or the text / code lines), provider fallback, save an answer
  as a note.
- **Knowledge graph and wiki**: entities and relations from documents (LLM) and code (symbols, imports, calls —
  no model); wiki pages written only from the passages the reader may see; graph view; graph-expanded chat context.
- **Summaries and suggested questions** for every document.
- **Deep research mode**: plans sub-questions, searches each one in scope and writes a structured, cited report.
- **Multi-user**: projects, workspaces and notebooks with inherited viewer/editor/owner roles shared with users or
  groups; single sign-on (OpenID Connect, e.g. Keycloak) with group sync; audit log.
- **Governance**: per-project provider policy (e.g. "LAN only"); changing the embedding model re-indexes with no
  search downtime (atomic index switch).
- Light and dark theme.

## Quick start

Requirements: Docker Engine with the Compose plugin (v2.23+), 4 GB RAM (8 GB recommended), outbound HTTPS to your
model providers.

```bash
mkdir opennotebook && cd opennotebook
BASE=https://raw.githubusercontent.com/lordraw77/OpenNotebook/HEAD
curl -fsSLO $BASE/deploy/production/docker-compose.yml
curl -fsSLO $BASE/.env.example
curl -fsSL  $BASE/scripts/gen-secrets.sh -o gen-secrets.sh && chmod +x gen-secrets.sh
./gen-secrets.sh .env      # creates .env and generates every internal secret + the first admin password
$EDITOR .env               # BOOTSTRAP_ADMIN_EMAIL, at least one provider key, optional MODEL_* defaults
docker compose up -d
```

Open `http://<host>:8080` and sign in with `BOOTSTRAP_ADMIN_EMAIL` and the generated
`BOOTSTRAP_ADMIN_PASSWORD` (in `.env`). Then: **Settings → Providers** (check providers and models),
**Settings → Models** (chains per phase), **Workbench** (create a project, upload sources, ask).

The Compose file starts the three OpenNotebook images plus PostgreSQL 18, Qdrant, SeaweedFS (S3 storage) and
Redis. Optional profiles: `observability` (Prometheus, Grafana, Jaeger), `auth` (Keycloak) and `converter`
(office documents to PDF, with `CONVERTER_URL=http://converter:8080`):
`docker compose --profile observability up -d`.

## Tags

| Tag | Content |
|---|---|
| `1.2.0` | Iterative deep research, model-rewritten follow-ups, no double embedding on model change, chat history |
| `1.1.0` | Git repository sources with scheduled sync, native XLSX/PPTX import, editable knowledge graph |
| `1.0.1` | Rerank through Ollama-compatible proxies (llmproxy) |
| `1.0.0` | First stable release: observability, operations, isolated office converter, lazy source tree, Italian UI, Helm chart |
| `0.5.1` | Fix: sources can be uploaded to projects and workspaces, not only notebooks |
| `0.5.0` | M0–M5: adds groups, single sign-on (OIDC), provider policy per project, zero-downtime embedding change, deep research mode |
| `0.4.0` | M0–M4: foundations, ingestion, grounded chat, extended ingestion, knowledge graph and wiki |
| `latest` | The most recent release |

Pin an exact version in production (`VERSION=1.2.0` in `.env`). The three images of a deployment must have the
same version. Images are `linux/amd64`.

{{IMAGE_DETAILS}}

## Security

- Runs as a non-root user; the Compose file adds a read-only root filesystem, `no-new-privileges` and drops all
  capabilities.
- Databases and storage sit on an internal network without internet access; only the web port is published.
- Provider API keys are stored encrypted (AES-GCM) with `APP_ENCRYPTION_KEY` — back that key up together with
  the `pg-data` volume.
- Strict Content-Security-Policy in the web UI; uploaded content is treated as untrusted (archive limits, SSRF
  protection, prompt-injection-aware prompts).

## Data and backup

Volumes: `pg-data` (source of truth), `blob-data` (original files), `qdrant-data` (vector index, rebuildable by
re-indexing), `redis-data` (queues). Back up `pg-data`, `blob-data` and `APP_ENCRYPTION_KEY`.

## Upgrade

Set the new `VERSION` in `.env`, then `docker compose pull && docker compose up -d`. Database migrations run
automatically in the `migrate` job before the api and worker start.

## Documentation and source

- Source code, issues and full documentation: <https://github.com/lordraw77/OpenNotebook>
- Deployment guide: `docs/deploy.md` · Docker overview (services, profiles, volumes, troubleshooting):
  `docs/docker.md` · Architecture and threat model: `docs/analysis/`
