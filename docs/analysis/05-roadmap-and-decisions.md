# 05 — Roadmap and Open Decisions

> Status: draft v0.2 — 2026-11-05.

## 1. Milestones

| Milestone | Content | Verifiable result |
|---|---|---|
| **M0 — Foundations** ✅ (2026-11-05) | Monorepo (`backend/`, `frontend/`, `deploy/`, `docs/`), Dockerfiles for every service, Compose stack, Makefile, FastAPI + Alembic + `migrate` job, Angular + PrimeNG skeleton, local auth, CI (lint, test, image build). | `make up` starts the stack on a clean host; all health checks green; login works (US-10 partially). |
| **M1 — Hierarchy, providers, basic ingestion** ✅ (2026-11-06) | Nodes + ACL, provider registry for the 9 providers, per-phase assignment with fallback, PDF/TXT/MD/DOCX upload, manual notes, pdfplumber parsing, chunking, external embeddings + BM25 sparse vectors, Qdrant, SeaweedFS, Upload page and minimal RAG Status page. | A source reaches `ready` with visible chunks; "Test connection" passes for each configured provider. |
| **M2 — Grounded chat** ✅ (2026-11-06) | Hybrid retrieval + rerank, scope and switches, strict prompt, validated citations, SSE, PDF/text viewer with highlighting, 3-column Workbench, save answer as note. | US-01, US-02, US-03, US-09 pass. |
| **M3 — Extended ingestion** ✅ (2026-11-08) | Archives (hardened), code (tree-sitter), images (OCR + vision), web scraping (SSRF-safe), summary and suggested questions. | US-04, US-05, US-06 pass. |
| **M4 — Graph and wiki** ✅ (2026-11-08) | Entity/relation extraction, code graph, graph-based retrieval expansion, navigable wiki pages, graph view. | Multi-hop questions improve on the eval set. |
| **M5 — Advanced research and administration** ✅ (2026-11-08) | Multi-step agent / cited report, encrypted key management UI, groups and full permissions, OIDC, per-project provider policy. | US-07, US-08 pass. |
| **M6 — Production** ✅ (2026-11-09) | Observability (OTel, dashboards, alerts, SLOs), hardening, load tests, backup/restore, release bundle, operations docs, first release. | Runbooks and SLOs defined; `make bundle` installs on a host without registry access. |

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

- ~~Follow-up questions are not rewritten by a model~~ Since 1.2 a model rewrites a follow-up into a standalone
  search query (`CHAT_REWRITE_FOLLOWUPS`); if that call fails, a short follow-up is searched together with the
  previous question as before.
- Groundedness is checked structurally (valid markers, uncited sentences, abstention), not by a judge model.
- Citations of a chunk that spans several PDF pages open its first page; since 1.2 the viewer says "This passage
  spans pages 3 4" with one button per page, and the passage's boxes are highlighted on each of them.
- The automated RAG quality evaluation (recall@k, citation accuracy, abstention rate on a fixed corpus) is still
  to be built; the M2 tests cover the mechanics with scripted models, plus a manual check on real providers.

## 2.3 Known limitations after M3

- **No 7z / RAR** (py7zr is LGPL with several native dependencies; RAR has no permissive extractor): ZIP and TAR
  only. Single compressed files (`.gz` without TAR) are refused.
- **No JavaScript rendering** of web pages (Playwright would add a browser to the worker image): pages that render
  their content client-side yield little or no text.
- **Office → PDF conversion** is the optional `converter` service (shipped after M6, see below); without it DOCX
  citations open the text viewer, and PPTX, XLSX, ODF and legacy Office files are refused.
- Images embedded in PDF/DOCX are not extracted (only scanned pages are transcribed); OCR text is anchored to the
  whole page or image, not to word boxes.
- Archive extraction holds the archive in memory (up to `UPLOAD_MAX_MB`); members are streamed with byte limits.
- The source list and tree load every source of the visible notebooks: an archive with thousands of files makes
  them heavy (pagination / lazy tree loading planned).

## 2.4 Known limitations after M4

- Entity resolution is by normalized name only: abbreviations and synonyms ("AP" / "access point") stay separate
  entities.
- No community detection or topic pages; the wiki has one page per entity.
- Graph extraction costs one model call per ~8000 characters; large corpora need a fast, cheap model for the
  `graph_extraction` phase. Sources indexed before M4 need **Rebuild graph**.
- The graph view shows the 150 most-mentioned entities of the scope; there is no server-side neighbourhood
  exploration yet.
- Code calls are resolved by name (same file, or a unique function name in the project); dynamic dispatch and
  overloaded names are not resolved.
- The "multi-hop questions improve on the eval set" exit criterion still needs the RAG evaluation set (see M2
  limitations); graph expansion is verified by tests and by manual checks.

## 2.5 Known limitations after M5

- Provider keys are managed encrypted in Settings → Providers (since M0). Rotating `APP_ENCRYPTION_KEY` itself
  (re-encrypting the stored keys) is not automated yet (M6).
- ~~The deep research agent is a fixed plan → retrieve → write pipeline~~ Since 1.2 it reads what it found and
  searches again for what is missing (`RESEARCH_MAX_ROUNDS`, default 2): each round costs one short model call and
  one retrieval per new question.
- OIDC: no RP-initiated logout (signing out of OpenNotebook does not end the IdP session), no back-channel
  logout; group sync happens at sign-in only.
- The provider policy restricts providers, not individual models; an empty policy blocks the project entirely.
- ~~During an embedding change, sources whose content changed are embedded twice~~ Since 1.2 a source is embedded
  with the new model only; searches query both indexes while the change is running and fuse them by rank.

## 2.6 State after M6

Exit criteria: runbooks and SLOs are defined ([../operations/](../operations/README.md)); `make bundle`
installs on a host without registry access (verified). Load test, backup/restore and the RAG evaluation set were
run on the test host; results in [../operations/performance.md](../operations/performance.md) and
[../operations/rag-evaluation.md](../operations/rag-evaluation.md).

Still open (candidates for the next iterations):

- Network-less parsing worker for the deterministic parsers (T5 residual; LibreOffice is already isolated in the
  `converter` service).
- A larger evaluation corpus to measure the effect of graph expansion on multi-hop questions.

## 3. Open decisions

Also pending on the operator side: the Hugging Face token in the test `.env` is expired (HTTP 401).

| # | Question | Proposed default |
|---|---|---|
| D2 | Can a source belong to multiple notebooks at the same time? | No in v1 (logical copy without re-embedding if needed). |
| D4 | ~~Graph: PostgreSQL (simpler) or Neo4j (rich graph queries and visualization)?~~ | Resolved in M4: PostgreSQL (1-hop expansion and per-entity reads are all that is needed so far). |
| D5 | Vector DB: Qdrant (proposed) or pgvector to reduce components? | Qdrant. |
| D6 | ~~Authentication: local users, OIDC/Keycloak, corporate LDAP/AD?~~ | Resolved in M5: local passwords and/or OIDC (`AUTH_MODE`); LDAP/AD through the IdP (e.g. Keycloak user federation). |
| D7 | ~~Confidentiality constraints: which projects may use cloud providers?~~ | Resolved in M5: all allowed by default; per-project provider policy (Project settings). |
| D8 | Expected volumes: users, documents, max archive size? | 50 users, 1M chunks, archives ≤ 2 GB uncompressed. |
| D9 | Container registry for published images (GHCR, Docker Hub, private)? | GHCR. |
| D10 | ~~Is multi-page web crawling needed in v1, or single URLs only?~~ | Resolved in M3: single URLs plus an optional bounded crawl (same site, depth ≤ 2, page budget, robots.txt). |
| D12 | ~~Is sending content to cloud providers acceptable for all projects?~~ | Resolved in M5 with the provider policy (e.g. a project restricted to the LAN Ollama). |
