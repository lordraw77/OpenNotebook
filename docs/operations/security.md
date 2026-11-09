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

None at the moment (`.pip-audit-ignore` and `.trivyignore` are empty).

Resolved: 13 CVEs of `filelock` < 4.2.1, a transitive dependency of LiteLLM, are fixed by forcing
`filelock==4.2.1` with a uv override (`[tool.uv] override-dependencies` in `backend/pyproject.toml`): LiteLLM
1.108.0 declares `filelock<4`, while LiteLLM 1.108.3 relaxed it to `<5`. Remove the override when LiteLLM is
upgraded.

## Reporting

Report vulnerabilities privately to the maintainers (GitHub security advisory on the repository), not in
public issues.
