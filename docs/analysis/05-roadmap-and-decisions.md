# 05 — Roadmap and Open Decisions

> Status: draft v0.2 — 2026-11-05.

## 1. Milestones

| Milestone | Content | Verifiable result |
|---|---|---|
| **M0 — Foundations** ✅ (2026-11-05) | Monorepo (`backend/`, `frontend/`, `deploy/`, `docs/`), Dockerfiles for every service, Compose stack, Makefile, FastAPI + Alembic + `migrate` job, Angular + PrimeNG skeleton, local auth, CI (lint, test, image build). | `make up` starts the stack on a clean host; all health checks green; login works (US-10 partially). |
| **M1 — Hierarchy, providers, basic ingestion** ✅ (2026-11-06) | Nodes + ACL, provider registry for the 9 providers, per-phase assignment with fallback, PDF/TXT/MD/DOCX upload, manual notes, pdfplumber parsing, chunking, external embeddings + BM25 sparse vectors, Qdrant, SeaweedFS, Upload page and minimal RAG Status page. | A source reaches `ready` with visible chunks; "Test connection" passes for each configured provider. |
| **M2 — Grounded chat** ✅ (2026-11-06) | Hybrid retrieval + rerank, scope and switches, strict prompt, validated citations, SSE, PDF/text viewer with highlighting, 3-column Workbench, save answer as note. | US-01, US-02, US-03, US-09 pass. |
| **M3 — Extended ingestion** ✅ (2026-11-08) | Archives (hardened), code (tree-sitter), images (OCR + vision), web scraping (SSRF-safe), summary and suggested questions. | US-04, US-05, US-06 pass. |
| **M4 — Graph and wiki** | Entity/relation extraction, code graph, graph-based retrieval expansion, navigable wiki pages, graph view. | Multi-hop questions improve on the eval set. |
| **M5 — Advanced research and administration** | Multi-step agent / cited report, encrypted key management UI, groups and full permissions, OIDC, per-project provider policy. | US-07, US-08 pass. |
| **M6 — Production** | Observability (OTel, dashboards, alerts, SLOs), hardening, load tests, backup/restore, release bundle, operations docs, first release. | Runbooks and SLOs defined; `make bundle` installs on a host without registry access. |

Continuous RAG quality evaluation from M2: a question/expected-answer dataset per test corpus, measuring recall@k, citation accuracy and correct-abstention rate.

## 2. Resolved decisions

| # | Decision |
|---|---|
| R1 | All documentation, code comments and default UI strings are in English. |
| R2 | MinIO is replaced by **SeaweedFS** (S3 API) behind a `BlobStore` interface; Garage, external S3 and local filesystem are alternatives (ADR-007). |
| R3 | Everything ships as container images and starts with one command, from a single Compose file with optional profiles (architecture §7, [../docker.md](../docker.md)). |
| R4 | **No models inside the project**: no model weights, no inference containers, no ML runtimes. Every model call (LLM, embedding, rerank, vision, OCR) goes to an external provider (ADR-008). |
| R5 | Supported providers: Groq, OpenRouter, Gemini, Cloudflare Workers AI, Cerebras, Mistral, NVIDIA, Hugging Face, Ollama (ADR-005). |
| R7 | **D1 resolved**: free nesting of workspaces and notebooks (SCP-01). |
| R8 | **D3 resolved**: the embedding model (like every phase) is configurable globally and **per project** (ADR-012). |
| R9 | **D11 resolved**: `.gitignore` rewritten for OpenNotebook; backend package `opennotebook`. |
| R10 | UI library: Angular 22 + Angular Material instead of PrimeNG, because PrimeNG ≥ 22 requires a commercial license key (ADR-011). |
| R6 | Ollama is only the user's external test instance on the LAN (slow, CPU-only); the stack never deploys Ollama. It is not in the default fallback chains. |

## 2.1 Known limitations after M1

- Re-indexing after an embedding change is per source, not an atomic switch: until a source is re-indexed it is not
  found by searches that use the new model (US-08 atomic alias switch is deferred to M6). The RAG Status page shows
  the sources that need re-indexing and offers a per-project re-index.
- DOCX and Markdown sources carry character offsets and lines, not pages: their citations open the text viewer.
- Scanned PDF pages (no text layer) are reported as a warning; OCR arrives in M3.

## 2.2 Known limitations after M2

- Follow-up questions are not rewritten by a model: a short follow-up is searched together with the previous
  question. Rewriting and decomposition come with the advanced mode (M5).
- Groundedness is checked structurally (valid markers, uncited sentences, abstention), not by a judge model.
- Citations of a chunk that spans several PDF pages open its first page; the pager shows the other pages, and
  their boxes are highlighted too.
- The automated RAG quality evaluation (recall@k, citation accuracy, abstention rate on a fixed corpus) is still
  to be built; the M2 tests cover the mechanics with scripted models, plus a manual check on real providers.

## 2.3 Known limitations after M3

- **No 7z / RAR** (py7zr is LGPL with several native dependencies; RAR has no permissive extractor): ZIP and TAR
  only. Single compressed files (`.gz` without TAR) are refused.
- **No JavaScript rendering** of web pages (Playwright would add a browser to the worker image): pages that render
  their content client-side yield little or no text.
- **DOCX/PPTX/ODT → PDF conversion (LibreOffice) is not shipped**: it would add ~350 MB to the worker, and the
  converter must run without network access (documents can reference remote resources). It is planned as an
  optional, network-isolated converter service in M6; until then DOCX citations open the text viewer, and PPTX,
  XLSX and ODF are refused.
- Images embedded in PDF/DOCX are not extracted (only scanned pages are transcribed); OCR text is anchored to the
  whole page or image, not to word boxes.
- Archive extraction holds the archive in memory (up to `UPLOAD_MAX_MB`); members are streamed with byte limits.
- The source list and tree load every source of the visible notebooks: an archive with thousands of files makes
  them heavy (pagination / lazy tree loading planned).

## 3. Open decisions

Also pending on the operator side: the Hugging Face token in the test `.env` is expired (HTTP 401).

| # | Question | Proposed default |
|---|---|---|
| D2 | Can a source belong to multiple notebooks at the same time? | No in v1 (logical copy without re-embedding if needed). |
| D4 | Graph: PostgreSQL (simpler) or Neo4j (rich graph queries and visualization)? | PostgreSQL in v1. |
| D5 | Vector DB: Qdrant (proposed) or pgvector to reduce components? | Qdrant. |
| D6 | Authentication: local users, OIDC/Keycloak, corporate LDAP/AD? | Local + OIDC. |
| D7 | Confidentiality constraints: which projects may use cloud providers? | All allowed by default; per-project "local only" policy available. |
| D8 | Expected volumes: users, documents, max archive size? | 50 users, 1M chunks, archives ≤ 2 GB uncompressed. |
| D9 | Container registry for published images (GHCR, Docker Hub, private)? | GHCR. |
| D10 | ~~Is multi-page web crawling needed in v1, or single URLs only?~~ | Resolved in M3: single URLs plus an optional bounded crawl (same site, depth ≤ 2, page budget, robots.txt). |
| D12 | Is sending content to cloud providers acceptable for all projects, or are some projects restricted to the LAN Ollama only? | All cloud providers allowed by default; per-project allowlist available. |
