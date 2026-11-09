# Security Operations

Threat model and design: [../analysis/04-threat-model.md](../analysis/04-threat-model.md).

## Hardening in place

- Containers: non-root users, read-only root filesystem, all capabilities dropped, `no-new-privileges`,
  memory and PID limits (`*_MEM_LIMIT`), log rotation. Databases and storage on an internal network without
  internet access; only the web port is published (plus profile UIs on 127.0.0.1).
- Images: OS security updates applied at build time (`apt-get upgrade` / `apk upgrade`); no model weights or ML
  runtimes (`make check-no-models`).
- Web: strict Content-Security-Policy (`script-src 'self'`), `X-Frame-Options DENY`, no third-party
  assets; nginx re-resolves the api so restarts never route to a stale address. Add HSTS at your TLS proxy.
- Application: argon2 passwords, short-lived JWT, rotating HttpOnly refresh cookies, login rate limit, per-user
  chat/search/research limits, OIDC with PKCE, ACL pre-filter on every retrieval, SSRF-safe fetcher, archive
  bomb limits, encrypted provider keys with key rotation, audit log.

## Scanning (CI)

| Check | Tool | Policy |
|---|---|---|
| Python dependencies | `pip-audit` on the locked requirements | fail on any known vulnerability not listed in `.pip-audit-ignore` |
| JavaScript dependencies | `npm audit --omit=dev` | fail on high or critical |
| Images | Trivy (api, web) | fail on HIGH/CRITICAL with a fix available, except `.trivyignore` |
| SBOM | Syft (SPDX JSON) | published as a CI artifact |

## Accepted risks

| Id | Component | Why it is accepted | Review |
|---|---|---|---|
| CVE-2026-112907…112940 (13 ids, see `.pip-audit-ignore`) | `filelock` 3.32.7, pulled by LiteLLM 1.108 (`filelock<4`) through `huggingface-hub` | Local-user attacks (symlink / ACL races) on shared lock directories. Containers run a single non-root user with a private tmpfs `/tmp` and a read-only root; the lock code is only used by LiteLLM's proxy CLI and Hugging Face downloads, which OpenNotebook never runs. | when LiteLLM allows `filelock>=4.2.1` |

## Reporting

Report vulnerabilities privately to the maintainers (GitHub security advisory on the repository), not in
public issues.
