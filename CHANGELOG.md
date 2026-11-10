# Changelog

All notable changes. Images: `lordraw/opennotebook-{web,api,worker}` on Docker Hub.

## 1.3.0 — 2026-11-10

- 7z and RAR archives are extracted like ZIP and TAR (same limits: size, ratio, file count, depth, unsafe paths,
  links). They are read with libarchive (BSD licence), installed in the worker image (`libarchive13t64`); new
  dependency `libarchive-c`. Encrypted members are reported, not extracted. Dev-only: `py7zr` for tests.
- Pictures inside PDF and DOCX are read by the OCR/vision models and become text blocks at their position
  (`[Image]` description, `[Text in image]`); in PDF they carry the picture's box, so a citation highlights it.
  Settings `EMBEDDED_IMAGES` (default on, needs an OCR or vision model), `EMBEDDED_IMAGES_MAX` (20 per source),
  `EMBEDDED_IMAGE_MIN_PX` (64). Repeated pictures (logos), tiny ones and page-sized backgrounds are skipped; a
  failing model call only costs that picture. Slides/sheets (PPTX, XLSX) are not covered.
- OCR text is anchored to line boxes instead of the whole page: with `OCR_LAYOUT=auto` (default) a vision model is
  asked for the lines of a scanned page or image and their rectangles, and citations highlight those lines.
  `always` does it even when an OCR chain exists, `off` keeps whole-page anchors. A reply without usable boxes
  falls back to whole-page anchors with a warning. Dedicated OCR models (Mistral OCR) only return Markdown, so
  with them the anchor stays the whole page unless `OCR_LAYOUT=always`.
- In-app user guide (top bar → Guide) in English and Italian, following the interface language, with screenshots of
  the real interface in each language. `make docs-screenshots` regenerates them from a demo backend with scripted
  models (`scripts/docs/`).
- `VERSION`, Helm chart and compose defaults aligned with the release number.

## 1.2.0 — 2026-11-09

- Deep research reads what it found and searches again for what is missing (`RESEARCH_MAX_ROUNDS`, default 2;
  `RESEARCH_MAX_PASSAGES` now 30). New `reflecting` status and `plan` events with a `round`.
- Follow-up questions are rewritten by a model into a standalone search query (`CHAT_REWRITE_FOLLOWUPS`,
  `CHAT_REWRITE_TIMEOUT_S`): new `rewriting` status and `query` event, `checks.rewritten_query` on the answer;
  falls back to the previous behaviour when the call fails.
- Embedding model change: a source is embedded with the new model only. While the change runs, searches embed
  the query with both models, query both indexes and fuse the rankings, so nothing is embedded twice and
  sources added meanwhile are searchable at once. Old vectors of a re-indexed source are deleted.
- Citations over several PDF pages: the viewer lists the pages of the passage and jumps between them.
- Chat history: new page *History* (all conversations across scopes, search in messages, scope filter, date
  groups, open in its scope, delete, download as Markdown); `GET /api/conversations/history`,
  `GET /api/conversations/{id}/export`; the workbench accepts `?scope=&conversation=`.

## 1.1.0 — 2026-11-09

- Git repositories as sources (`POST /api/nodes/{id}/git`, `POST /api/sources/{id}/sync`,
  `PATCH /api/sources/{id}/git`): http(s) clone of one branch, access token stored encrypted, host allow-list
  `GIT_ALLOWED_HOSTS` (off by default), sync on request and on a schedule (`GIT_SYNC_SCHEDULER`, beat runs inside
  the worker), incremental by commit and file hash. The worker image now contains `git`.
- XLSX and PPTX are read directly: sheet/row and slide anchors, speaker notes, hidden sheets skipped, zip-bomb
  limit. `OFFICE_NATIVE=false` keeps the converter path. New dependencies: openpyxl, python-pptx, defusedxml.
- Editable knowledge graph: `PATCH/DELETE /api/entities/{id}`, `POST /api/entities/{id}/merge`,
  `POST /api/relations`, `DELETE /api/relations/{id}` (editor role on the project). Migration 0007; edits survive
  re-indexing (renames, merges, deleted entities and relations are remembered); manual relations take part in
  graph expansion of the chat context. UI: "Edit the graph" on the wiki page.

## 1.0.1 — 2026-11-09

- Rerank models of an Ollama provider are called through `POST <base_url>/rerank` (Jina/Cohere format), as served by
  Ollama-compatible proxies such as llmproxy; plain Ollama has no rerank API.

## 1.0.0 — 2026-11-09

Includes the M6 work below.

- Security: `filelock` 4.2.1 (13 CVEs fixed) through a uv override, while LiteLLM 1.108.0 still declares `<4`.
- Helm chart `deploy/helm/opennotebook` (NFR-08): application, migration Job, optional converter, bundled or external
  data services, Ingress, NetworkPolicies; new `opennotebook wait-migrations` command for init containers.
- RAG evaluation: second set `eval/graph` (24 documents, 16 questions, chains project -> lead -> system ->
  data centre) and context coverage via search versus graph (`scripts/rag_eval.py --set graph`); graph
  expansion now weighs seeds by the rank of their passage.
- Italian user interface (NFR-06): language switch in the top bar (browser language by default), Italian dates
  and numbers, translated server messages for the common cases; `scripts/check-i18n.mjs` in CI.
- Workbench: lazy source tree. Sources load per expanded node or archive, 100 per page with "Load more";
  `GET /api/sources` gains `node_id`, `parent_id`, `top_level`, `q`, `ids`, `offset`/`limit` (`X-Total-Count`) and
  `child_count`; new `GET /api/sources/counts`.
- Office documents: optional isolated `converter` service (headless LibreOffice, image
  `opennotebook-converter`, `converter` profile, `CONVERTER_URL`). PPTX, XLSX, ODT/ODP/ODS, DOC/XLS/PPT, RTF and
  DOCX become PDF renditions with page anchors and the PDF viewer (`GET /api/sources/{id}/view`). The converter
  runs alone on an internal `convert` network reachable only by the worker (threat T5).
- Tracing: database spans (operation and table only, no SQL text or parameters) from SQLAlchemy cursor events.

## M6 — production readiness (committed 2026-11-09)

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
  - `pip-audit`, `npm audit`, Trivy image scans and SPDX SBOM in CI.
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
