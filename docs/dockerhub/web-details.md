## About this image

- Angular single-page application served by `nginxinc/nginx-unprivileged` on port **8080** (non-root).
- nginx proxies `/api/` to `api:8000` without buffering (server-sent events for the chat stream) and adds the
  security headers (CSP `script-src 'self'`, `frame-ancestors 'none'`, `nosniff`, …) on every response.
- Fonts, icons and the pdf.js worker are bundled: the browser loads nothing from third-party CDNs.
- Health check: `GET /healthz`.
- Configuration: none of its own — publish it with `WEB_BIND` / `WEB_PORT` in `.env` and put a TLS reverse proxy
  in front of it for production.
