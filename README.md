# OpenNotebook

Self-hosted knowledge workspace with **grounded RAG chat** and **traceable citations**.

Upload documents, source code, archives, images, web pages and notes, organize them in a freely nested
**Project → Workspace → Notebook** tree, and chat with an LLM that answers **only** from the sources in the selected
scope. Every claim cites its source (`[Source 1, p. 4]`), and clicking a citation highlights the exact passage.

> **Status: milestones M0 (foundations), M1 (ingestion) and M2 (grounded chat) complete.** Runs today: the packaged
> stack, login, the hierarchy with sharing and on/off switches, the provider registry for nine providers, model
> selection per phase (global and per project), upload and indexing of PDF/DOCX/Markdown/text and notes, scoped
> hybrid search, and grounded chat with streaming answers, validated citations, provider fallback and a source
> viewer that highlights the cited passage. Extended ingestion (M3) is next.
> See the [roadmap](docs/analysis/05-roadmap-and-decisions.md).

## Features

| Area | Status |
|---|---|
| Packaged stack: one Compose file, optional profiles, health checks, `make` targets | ✅ M0 |
| Local users, rotating refresh tokens, login rate limiting, audit log | ✅ M0 |
| Hierarchy with free nesting, inherited permissions (viewer/editor/owner), sharing, active switches | ✅ M0 |
| Providers: Groq, OpenRouter, Gemini, Cloudflare Workers AI, Cerebras, Mistral, NVIDIA, Hugging Face, Ollama | ✅ M0 |
| Model catalog sync with capability detection, per-model test, encrypted keys | ✅ M0 |
| Model selection per phase with fallback chains; per-project overrides; chat model selector | ✅ M0 |
| Light and dark theme (follows the system, or chosen from the top bar); responsive header | ✅ M1 |
| Ingestion of PDF, TXT, Markdown, DOCX and notes; structure-aware chunking; embeddings per project; hybrid search with ACL pre-filter | ✅ M1 |
| Grounded chat: streaming answers, strict prompt, validated clickable citations, provider fallback, optional rerank, conversations, save answer as note | ✅ M2 |
| Source viewer: PDF page with the cited passage highlighted (pdf.js), text sources with the passage marked | ✅ M2 |
| Archives, source code, images (OCR + description), web pages, summaries | M3 |
| Knowledge graph and wiki pages | M4 |
| Deep research mode, OIDC, per-project provider policy | M5 |

## No models inside

OpenNotebook ships **no model weights, no inference containers and no ML runtimes** (checked by `make check-no-models`).
Every model call (chat, summaries, graph extraction, vision, OCR, embeddings, rerank) goes to an external provider:

| Provider | Typical phases |
|---|---|
| Groq | chat, summaries, graph extraction, vision |
| OpenRouter | chat, summaries, vision, embeddings |
| Google Gemini | chat, summaries, vision, embeddings |
| Cloudflare Workers AI | chat, embeddings, vision, rerank |
| Cerebras | chat, summaries, graph extraction |
| Mistral | chat, embeddings, vision, OCR |
| NVIDIA NIM | chat, embeddings, rerank, vision |
| Hugging Face | chat, embeddings |
| Ollama | any phase, on an existing external Ollama server |

A working instance needs at least one chat model and one embedding model (Gemini or Mistral alone covers both).

## Quick start

Requirements: Docker Engine with the Compose plugin, GNU make, 4 GB RAM (8 GB recommended), outbound HTTPS to your providers.

```bash
git clone <repository-url> opennotebook && cd opennotebook
make secrets        # creates .env from .env.example and generates internal secrets + first admin password
$EDITOR .env        # add provider keys; optionally MODEL_CHAT / MODEL_EMBEDDING defaults and BOOTSTRAP_ADMIN_EMAIL
make build          # builds web, api and worker images
make up             # starts the stack; open http://localhost:8080
```

Sign in with `BOOTSTRAP_ADMIN_EMAIL` and the generated `BOOTSTRAP_ADMIN_PASSWORD`. At first start the `migrate`
job applies migrations, creates the admin, imports every provider whose key is in `.env`, syncs their model catalogs
and applies the `MODEL_*` defaults.

Then, in the UI:

1. **Settings → Providers**: check each provider, enable the models you want, use **Test** on them.
2. **Settings → Models**: set the chain for each phase (global defaults, or per project).
3. **Workbench**: create a project, nest workspaces and notebooks, share them, upload sources.
4. Select a scope in the tree, pick the chat model and ask: every statement of the answer carries a citation
   chip; clicking it opens the source at the cited passage. **Save as note** keeps an answer with its citations.

Operations, profiles and volumes: [docs/docker.md](docs/docker.md).

## Model selection

- Each **phase** (chat, summary, graph extraction, image description, OCR, embedding, rerank) has an ordered
  **chain**: the first model is used, the next ones are fallbacks on errors, rate limits or timeouts.
- **Global defaults** are set by administrators; **project owners** can override any phase for their project,
  including a different embedding model. Embedding never falls back (vectors from different models do not mix).
- In the Workbench each user can choose the chat model among the enabled ones; the project chain is the default.
  If the chosen model fails before answering, the next model of the chain answers and the message shows which
  model was used.
- **Rerank** is optional: when a rerank model is assigned (NVIDIA, Cloudflare, Hugging Face, …) the retrieved
  passages are reordered before they reach the chat model; if it fails, the fusion order is kept.

## Development

```bash
# Backend (Python 3.12, uv)
cd backend && uv sync
make test/backend                       # tests against disposable PostgreSQL + Redis containers
DATABASE_URL=postgresql+psycopg://... uv run opennotebook api   # API on :8000 (other settings from env)

# Frontend (Node 24)
cd frontend && npm ci && npm start      # http://localhost:4200, proxies /api to 127.0.0.1:8000
npm test && npm run lint

make lint                               # ruff + prettier
make fmt                                # format everything
```

## Repository layout

```
backend/     FastAPI API, Celery worker, model gateway, Alembic migrations, tests
frontend/    Angular 22 + Angular Material web app, nginx config
deploy/      Docker Compose (single file with profiles), observability config
scripts/     secrets generation, tests, image checks, release bundle
docs/        analysis (requirements, architecture, data model, threat model, roadmap), Docker overview
```

## Documentation

- [Project analysis](docs/analysis/README.md): requirements, architecture and ADRs, data model, threat model, roadmap
- [Docker overview](docs/docker.md): images, services, profiles, volumes, operations

## License

To be defined. Third-party components are under permissive licenses (Angular and Angular Material: MIT;
Material Symbols: Apache-2.0; Roboto: OFL-1.1; pdf.js: Apache-2.0; SeaweedFS: Apache-2.0).
