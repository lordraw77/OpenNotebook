# 04 — Threat Model and Security Policy (Security Engineer)

> Status: draft v0.2 — 2026-11-05. Method: STRIDE over the main data flows.

## 1. Assets

Uploaded documents and code (potentially confidential), user credentials, model provider API keys, derived indexes and graph, chat history.

## 2. Trust boundaries

1. Browser ↔ api
2. api/worker ↔ uploaded content (**untrusted input**: files, archives, web pages)
3. worker ↔ internet (scraping)
4. api/worker ↔ external model providers (Groq, OpenRouter, Gemini, Cloudflare, Cerebras, Mistral, NVIDIA, Hugging Face): **data leaves the infrastructure**
5. api/worker ↔ Ollama on the LAN (often plain HTTP, unauthenticated)
6. Internal services (Postgres, Qdrant, Redis, SeaweedFS)

Every model call crosses boundary 4 or 5: no model runs inside the stack (ADR-008), so chunk text, images and questions are always sent to a provider.

## 3. Main threats and mitigations

| # | STRIDE | Threat | Mitigation |
|---|---|---|---|
| T1 | I | **Cross-scope data leak through RAG**: chunks from an unauthorized node reach the LLM context. | ACL filter inside vector/lexical/graph queries (ADR-006); dedicated regression tests; wiki/graph data scoped per project and filtered by visible mentions. |
| T2 | T/E | **Indirect prompt injection** from documents or web pages ("ignore your instructions and…"). | Sources wrapped as delimited data; system prompt declares them non-instructions; chat has no side-effecting tools; agent tools are read-only and bound to the authorized scope; output rendered as sanitized Markdown (no raw HTML/scripts, external links marked). |
| T3 | D | **Zip bombs / deeply nested archives**. | Limits on total uncompressed size, compression ratio, file count, depth; streaming extraction in a sandbox with a disk quota. |
| T4 | T/E | **Path traversal / links** in archives (`../../etc`). | Path normalization; reject absolute paths, `..`, symlinks and hardlinks; files never written under their original name (key = id). |
| T5 | E | **Parser exploits** (PDF, DOCX, images, LibreOffice). | Parsing worker in a non-root container, read-only root FS, no network (except the web-fetch worker), CPU/RAM/time limits, dependency updates; optional ClamAV. |
| T6 | I/E | **SSRF via scraping** (URLs to `169.254.169.254`, internal network, the Ollama host). | http/https only; DNS resolution and blocking of private/loopback/link-local ranges (re-checked after every redirect); dedicated egress; size and time limits. |
| T7 | S | Session / credential theft. | OIDC or argon2id passwords; short-lived JWT + refresh rotation; `HttpOnly`, `Secure`, `SameSite` cookies; login rate limiting; MFA via IdP. |
| T8 | I | **Provider API keys exposed**. | Envelope encryption with a master key from a mounted secret (or Vault/KMS); keys never returned by the API (last 4 chars only), never logged (log redaction filter on known key patterns: `gsk_`, `sk-or-`, `csk-`, `nvapi-`, `hf_`, …); `.env` git-ignored, `.env.example` without values. |
| T9 | I | Data sent to cloud providers not approved for a project. | Per-project provider allowlist (e.g. "LAN only": Ollama) enforced by the model gateway; UI badge showing where data is processed; provider used recorded on each message/job. |
| T10 | I | **Unencrypted Ollama traffic on the LAN**. | Document the risk; recommend a TLS reverse proxy or network isolation; allow restricting Ollama to non-sensitive projects. |
| T11 | E | IDOR on sources/notes/blobs (access by id). | Every endpoint resolves the resource's node and checks the role; presigned URLs only after the check and short-lived. |
| T12 | T | XSS from indexed content shown in the viewer. | HTML sanitization; web snapshots served in a sandboxed iframe with strict CSP; Angular safe bindings, no `bypassSecurityTrust*` on user content. |
| T13 | R | Untracked administrative actions. | Append-only `audit_log` for grants, provider config, key changes, deletions, exports. |
| T14 | D | Abuse of provider quotas / cost. | Per-user rate limits, token quotas, prioritized queues, timeouts; per-provider budget alerts. |
| T15 | T | **Supply chain**: compromised images or packages. The LLM gateway library (LiteLLM) handles every provider key, so it is a high-value target. | Exact pin of LiteLLM and hash-locked install from `uv.lock`; upgrades reviewed explicitly; pinned image tags (digests at release), lock files, SBOM, image scanning; no model weights are ever downloaded or loaded (`make check-no-models`, also in CI). |
| T16 | I | **Provider-side data retention / training** on submitted content. | Document each provider's data policy in Settings; prefer providers/plans with no-retention options for sensitive projects; per-project allowlist. |

### 3.1 Implementation status (M3)

- **T3 / T4 (archives)**: implemented without a disk: extraction is in memory with byte counting (declared sizes
  are not trusted), ratio, total-size, file-count and depth limits; unsafe names, links, devices and encrypted
  entries are skipped; blobs are stored under `sources/<id>/original`, never under the member name. Tests: zip
  bomb, path traversal, symlinks (ZIP and TAR), file count.
- **T5 (parsers)**: the worker runs non-root with a read-only root filesystem and no capabilities; images are
  bounded by `IMAGE_MAX_PIXELS` (decompression bombs). The worker keeps egress because it calls the providers and
  fetches web pages. The riskiest parser, LibreOffice (office formats other than DOCX), never runs in the worker:
  it runs in the optional `converter` container, alone on the `convert` network (`internal: true`), reachable
  only by the worker, with no internet, database or object-storage access, non-root, read-only root FS, no
  capabilities, memory/PID limits and a per-conversion timeout that kills the process group; macros never run.
  A compromised converter can only return a malicious PDF, which pdfplumber then parses under the worker's limits.
  Residual: the deterministic parsers (pdfplumber, python-docx, Pillow, tree-sitter) still run inside the worker,
  which has egress; moving them to a network-less parsing worker remains possible future work.
- **Git sources (SSRF, malicious repositories)**: `ingestion/git.py`. Only `http`/`https`, no credentials in the
  URL, and the host (and port) must be listed in `GIT_ALLOWED_HOSTS` (empty = off), checked when the source is
  added and at every sync; git runs with `GIT_ALLOW_PROTOCOL=http:https`, no hooks, no submodules, no
  redirects, no prompts, no system or user configuration, symlinks neither created nor read, a time limit and
  limits on the number and size of the files read. The access token is stored encrypted (like provider keys),
  passed to git as an HTTP header through the process environment (never in the command line) and removed from
  error messages. Residual: git connects by itself, so a DNS answer for an allow-listed name is trusted.
- **T6 (SSRF)**: implemented in `ingestion/web.py`: http(s) only, no credentials, all resolved addresses must be
  public (loopback, private, link-local incl. `169.254.169.254`, multicast, reserved, IPv4-mapped refused), the
  connected peer is re-checked (DNS rebinding), redirects re-validated hop by hop, size/time limits, no environment
  proxies. `WEB_ALLOW_PRIVATE=true` disables the address check for intranet use. Verified on the test stack:
  `http://192.168.0.215:18080/` and `http://169.254.169.254/` are refused.
- **T2 (prompt injection)** for summaries: document text is wrapped in a `<document>` block declared as data, and
  the reply must be JSON (anything else is discarded).

### 3.2 Implementation status (M4)

- **T1 for the knowledge graph**: entities are shared per project but carry no text; names, descriptions,
  relations and wiki pages are derived only from mentions and relations whose evidence source is visible to the
  reader (`visibility.py`). Wiki pages are cached per set of visible passages. Tests: a user who can read only
  `docs` sees neither entities nor relations nor wiki text derived from `source`. Switching a source or node off
  removes its contribution, and graph expansion in the chat never leaves the scope.
- **T2**: extraction and wiki prompts wrap passages as data and require JSON / cited text; unreadable replies are
  discarded.

### 3.3 Implementation status (M5)

- **T7**: OIDC with PKCE, state and nonce; ID token verified (JWKS signature, issuer, audience, expiry); no open
  redirect after sign-in; unverified emails refused by default; `AUTH_MODE=oidc` disables passwords. Tests use a
  scripted IdP (forged state, nonce, audience and expiry are rejected), and Keycloak was checked end-to-end.
- **T9**: per-project provider policy enforced in the model gateway for every call; the provider used is
  recorded on each message and job.
- **T1 with groups**: group grants go through the same pre-filter; a group reading only `documentation` never
  sees `source` in the tree, search, chat, research or graph (US-07).

### 3.4 Implementation status (M6)

- **T14**: per-user rate limits on chat, deep research and search (Redis, fail-open if Redis is down).
- **T15**: dependency audit (`pip-audit`, `npm audit`), image scanning (Trivy) and SBOM in CI; OS security
  updates applied at image build; no accepted exceptions at the moment
  ([../operations/security.md](../operations/security.md)).
- **T8**: `APP_ENCRYPTION_KEY` rotation (`rotate-encryption-key`, all or nothing, previous key accepted during
  the change).
- **T5 / D (denial of service)**: memory and PID limits per container.
- Backups contain `.env` in clear: the runbook requires encrypted, off-host storage.

## 4. Policies

- **Least privilege**: each service has its own DB credentials with minimal rights; Qdrant, Redis and SeaweedFS are reachable only on the internal Docker network, with authentication enabled.
- **Encryption**: TLS for all external traffic (reverse proxy); at rest via volume encryption + application-level encryption of secrets.
- **Secrets**: never in the repository; local `.env` (git-ignored) documented by `.env.example`; Docker secrets or Vault in production.
- **Supply chain**: lock files (uv, package-lock), `pip-audit` / `npm audit`, SBOM (Syft), image scanning (Trivy), base images pinned by digest.
- **Input validation**: Pydantic on every API; server-side MIME sniffing; configurable upload limits.
- **Privacy**: deleting a source also removes vectors, chunks, derived entities and blobs (verifiable on the RAG Status page).

## 5. Planned security tests

ACL regression suite (user without rights on branch X → 0 chunks from X over 100 queries), malicious archive fixtures, SSRF URL fixtures,
prompt-injection payloads inside test documents, secret-redaction tests on logs, DAST scan (OWASP ZAP) in CI.
