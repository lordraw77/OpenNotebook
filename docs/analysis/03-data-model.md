# 03 — Data Model (Data Engineer / DBA)

> Status: draft v0.2 — 2026-11-05. Logical schema; Alembic migrations will be generated at bootstrap.

## 1. Main entities (PostgreSQL)

```
users ──< group_members >── groups
  │                            │
  └──────< node_grants >───────┘   (principal = user | group, role, node)
                │
nodes (project | workspace | notebook)  ── self-ref parent_id, ltree path
  │
  ├──< sources ──< source_blobs (originals/derivatives in object storage)
  │       │  └── parent_source_id (files extracted from archives)
  │       ├──< chunks
  │       ├──< source_summaries (summary + suggested questions)
  │       └──< ingestion_jobs
  ├──< notes
  └──< conversations ──< messages ──< message_citations >── chunks

entities ──< entity_mentions >── chunks
entities ──< relations >── entities
wiki_pages (per entity / community)

providers ──< provider_models (capabilities)
phase_assignments (phase → ordered list of provider_models = fallback chain)
secrets (encrypted)
audit_log
```

## 2. Tables (excerpt)

```sql
CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TYPE node_kind AS ENUM ('project','workspace','notebook');

CREATE TABLE nodes (
  id          uuid PRIMARY KEY,
  kind        node_kind NOT NULL,
  parent_id   uuid REFERENCES nodes(id) ON DELETE RESTRICT,
  name        text NOT NULL,
  slug        text NOT NULL,
  path        ltree NOT NULL,              -- one label per level: n<uuid-hex>.n<uuid-hex>... (ids, not names: renames need no cascade)
  depth       int NOT NULL,                -- 0 for projects; free nesting below, max NODE_MAX_DEPTH
  active      boolean NOT NULL DEFAULT true,
  created_by  uuid REFERENCES users(id),
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now(),
  deleted_at  timestamptz,
  UNIQUE (parent_id, slug),
  CHECK ( (kind='project' AND parent_id IS NULL) OR (kind<>'project' AND parent_id IS NOT NULL) )
);
CREATE INDEX nodes_path_gist ON nodes USING gist (path);

CREATE TYPE source_kind   AS ENUM ('file','code','image','web','note','archive');
CREATE TYPE source_status AS ENUM ('queued','parsing','chunking','embedding','graph','summarizing','ready','failed','skipped');

CREATE TABLE sources (
  id               uuid PRIMARY KEY,
  notebook_id      uuid NOT NULL REFERENCES nodes(id),
  parent_source_id uuid REFERENCES sources(id) ON DELETE CASCADE,   -- archive children
  kind             source_kind NOT NULL,
  title            text NOT NULL,
  original_path    text,             -- e.g. firmware.zip!/src/radio.c
  uri              text,             -- URL for web sources
  mime_type        text,
  language         text,             -- natural or programming language
  content_sha256   bytea NOT NULL,
  size_bytes       bigint,
  active           boolean NOT NULL DEFAULT true,
  status           source_status NOT NULL DEFAULT 'queued',
  error            jsonb,
  pipeline_version text,
  metadata         jsonb NOT NULL DEFAULT '{}',
  created_by       uuid REFERENCES users(id),
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  deleted_at       timestamptz,
  UNIQUE (notebook_id, content_sha256, original_path)
);
CREATE INDEX sources_notebook_idx ON sources (notebook_id) WHERE deleted_at IS NULL;
CREATE INDEX sources_status_idx   ON sources (status) WHERE status NOT IN ('ready','skipped');

CREATE TABLE chunks (
  id            uuid PRIMARY KEY,
  source_id     uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  ordinal       int  NOT NULL,
  text          text NOT NULL,
  heading_path  text[],
  page_start    int, page_end int,
  bboxes        jsonb,               -- [{page, x0, y0, x1, y1}]
  char_start    int, char_end int,
  line_start    int, line_end int,
  token_count   int,
  block_type    text,                -- paragraph | table | code | ocr | image_description ...
  tsv           tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
  UNIQUE (source_id, ordinal)
);
CREATE INDEX chunks_tsv_gin ON chunks USING gin (tsv);

-- Nesting rules (enforced by the API): project = root; workspace under project|workspace;
-- notebook under project|workspace|notebook. Moves rewrite the subtree path in one UPDATE and stay in the project.

CREATE TYPE grant_role AS ENUM ('viewer','editor','owner');
CREATE TABLE node_grants (
  node_id        uuid NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  principal_type text NOT NULL CHECK (principal_type IN ('user','group')),
  principal_id   uuid NOT NULL,
  role           grant_role NOT NULL,
  PRIMARY KEY (node_id, principal_type, principal_id)
);

-- Model providers
CREATE TYPE provider_kind AS ENUM
  ('groq','openrouter','gemini','cloudflare','cerebras','mistral','nvidia','huggingface','ollama');
CREATE TYPE model_phase AS ENUM
  ('embedding','rerank','chat','summary','vision','ocr','graph_extraction');

CREATE TABLE providers (
  id          uuid PRIMARY KEY,
  kind        provider_kind NOT NULL,
  name        text NOT NULL UNIQUE,
  base_url    text,                         -- Ollama, HF endpoints, custom gateways
  secret_id   uuid REFERENCES secrets(id),  -- API key (encrypted)
  options     jsonb NOT NULL DEFAULT '{}',  -- e.g. {"account_id": "..."} for Cloudflare
  enabled     boolean NOT NULL DEFAULT true,
  rate_limit  jsonb,                        -- {"rpm": 30, "tpm": 60000}
  timeout_s   int NOT NULL DEFAULT 60
);

CREATE TABLE provider_models (
  id            uuid PRIMARY KEY,
  provider_id   uuid NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
  model         text NOT NULL,              -- provider-native model id
  capabilities  model_phase[] NOT NULL,
  context_window int,
  embedding_dim  int,
  UNIQUE (provider_id, model)
);

CREATE TABLE phase_assignments (
  phase          model_phase NOT NULL,
  project_id     uuid REFERENCES nodes(id), -- NULL = global default, otherwise per-project override
  position       int NOT NULL,              -- 0 = primary, 1.. = fallbacks
  model_id       uuid NOT NULL REFERENCES provider_models(id),
  params         jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (phase, project_id, position)
);
```

Other tables (summary): `users`, `groups`, `group_members`,
`source_blobs(source_id, role[original|derived_pdf|snapshot_html|snapshot_pdf|image], object_key, sha256, size)`,
`source_summaries`, `ingestion_jobs(id, source_id, step, status, attempts, provider_used, started_at, finished_at, error)`,
`notes(id, notebook_id, title, body_md, origin[manual|chat], citations jsonb, indexed bool)`,
`conversations(id, scope_node_id, user_id)`, `messages(id, conversation_id, role, content, provider_model_id, usage jsonb, latency_ms)`,
`message_citations(message_id, n, chunk_id)`, `entities(id, project_id, name, type, aliases, description)`,
`entity_mentions(entity_id, chunk_id)`, `relations(src, dst, type, weight, evidence_chunk_id)`,
`wiki_pages(id, project_id, entity_id | community_id, body_md, generated_at)`,
`secrets(id, ciphertext, nonce, key_version, created_at)`, `audit_log`.

Implemented in migration `0001` (M0): `users`, `groups`, `group_members`, `refresh_tokens` (hashed, rotated), `nodes`, `node_grants`,
`secrets` (AES-256-GCM ciphertext + nonce + display hint), `providers`, `provider_models` (capabilities, `capabilities_source`
inferred|provider|manual, `available`), `phase_assignments` (surrogate id + partial unique indexes for global and per-project chains), `audit_log`.
Implemented in migration `0002` (M1): `sources` (status, error, warnings, embedding model and vector collection used,
chunk and page counts, soft delete, unique content hash per notebook), `source_blobs` (original file and extracted
text), `chunks` (text, heading path, pages, bboxes, char offsets, lines, estimated tokens, generated `tsvector`),
`ingestion_jobs` (one row per attempt) and `notes` (an indexed note is mirrored by a source of kind `note`).
Implemented in migration `0003` (M2): `conversations` (owner, scope node, title) and `messages` (role, content,
status `complete|error|stopped`, `context` = passages given to the model, `citations` = validated passages used,
`checks`, model used, fallback attempts, usage, latency, error). Citations are stored as JSONB snapshots on the
message instead of a `message_citations` table, so they stay resolvable after a source is re-indexed (new chunk
ids) or deleted. Notes saved from the chat (`origin = chat`) copy those citations.
Implemented in migration `0004` (M3): `sources.summary`, `suggested_questions`, `summary_status`, `summary_model`,
`summary_error` (instead of a separate `source_summaries` table: one summary per source), and a partial index on
`parent_source_id` (archive members, crawled pages). Archive manifests, web fetch details and crawl settings live
in `sources.metadata` (`archive`, `final_url`, `content_type`, `fetched_at`, `crawl`). Web sources store
`sha256("url:" + normalized URL)` as `content_sha256`, so the notebook-level uniqueness deduplicates URLs.
Implemented in migration `0005` (M4): `entities` (project, canonical name unique per project, name, type; no
description: it lives on mentions), `entity_mentions` (entity, chunk, source, surface name, description),
`relations` (src, dst, type, description, evidence chunk and source), `wiki_pages` (entity, `basis` = hash of the
passages used, body, citations), and `sources.graph_status` / `graph_model` / `graph_error`. Mentions and relations
cascade with their chunks; visibility is derived from the evidence source (see architecture §4.2).
Implemented in migration `0006` (M5): `groups.description`, `groups.source` (`local` | `oidc`),
`users.oidc_subject` (unique), and `project_settings(project_id, allowed_provider_ids, embedding_model_id,
index_switched_at)`: the provider policy and the embedding model whose index serves searches (backfilled for
existing projects from their indexed sources). Chunk ids are now deterministic (uuid5 of source, ordinal and text
hash).
The other tables arrive with their milestone.

## 3. Scope and permission rules

- **Descendants of a scope**: `SELECT id FROM nodes WHERE path <@ :scope_path AND deleted_at IS NULL`.
- **Effective role** on a node = highest role among the user's (and their groups') grants on the node **or any ancestor** (downward inheritance). v1 has no explicit "deny"; to exclude a sub-branch, grant only the desired branches.
- **Readable nodes** per user are computed on demand and cached in Redis (invalidated on grant or tree changes).
- **Effective active state** of a source = `source.active AND all ancestors active`.

## 4. Qdrant payload

```json
{
  "chunk_id": "uuid", "source_id": "uuid",
  "ancestors": ["project_uuid", "workspace_uuid", "notebook_uuid"],
  "active": true,
  "kind": "code", "language": "c",
  "page": 4
}
```
- Payload indexes: `ancestors` (keyword), `source_id` (keyword), `active` (bool).
- Source/node toggle → `set_payload active` filtered by `source_id` / `ancestors`.
- Notebook move → `set_payload ancestors` filtered by `ancestors contains notebook_id`.
- One collection per embedding model: `chunks__<model_slug>__v<n>`; alias `chunks_current` switched atomically after re-index.
- Collection vector size comes from `provider_models.embedding_dim`.

## 5. Object storage (S3 API — SeaweedFS by default)

Keys: `sources/{source_id}/original`, `sources/{source_id}/derived.pdf`, `sources/{source_id}/snapshot.html`,
`sources/{source_id}/images/{n}.png`. Single private bucket (`opennotebook`); access only through the API
(short-lived presigned URLs after the ACL check, or streamed by the API). The `filesystem` backend uses the same key layout under a mounted volume.

## 6. Migrations and integrity

- Alembic, idempotent and backward-compatible migrations (expand → migrate → contract) for zero downtime; executed by the one-shot `migrate` container.
- Deletion: soft delete on nodes/sources → purge job removing vectors, blobs and orphan entities.
- Periodic Postgres ↔ Qdrant ↔ object storage reconciliation (counts per source), shown on the RAG Status page.

## 7. Sizing (indicative)

1M chunks × 1024-dim float32 dense vectors (≈ 4 KB each) ≈ 4 GB + sparse + HNSW → ~6–8 GB RAM in Qdrant; int8 scalar quantization reduces it to roughly a quarter.
