## About this image

- Enabled by the `converter` Compose profile; the worker uses it when `CONVERTER_URL=http://converter:8080`.
- Isolation (threat T5): LibreOffice parses untrusted files, so the container sits alone on the `convert`
  network (`internal: true`: no internet, no database, no object storage), reachable only by the worker. It runs
  as a non-root user with a read-only root filesystem, no capabilities and memory/PID limits.
- `POST /convert?ext=<docx|pptx|xlsx|odt|odp|ods|doc|xls|ppt|rtf>` with the document as body returns the PDF;
  `GET /health`. Each conversion has its own temporary LibreOffice profile and a timeout that kills the whole
  process group. Macros are never run.
- Settings: `CONVERTER_CONCURRENCY` (default 2), `CONVERTER_TIMEOUT_SECONDS` (180), `CONVERTER_MAX_MB`.
- No models inside: metric-compatible fonts (Liberation, Carlito, Caladea, DejaVu) keep page breaks close to
  Office.
