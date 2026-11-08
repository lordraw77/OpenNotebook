## About this image

- Same code and dependencies as `opennotebook-api`, started with the `worker` command; queues: `default`,
  `parse`, `ocr_vision`, `embed`, `graph`, `summary`.
- Deterministic parsers only: pdfplumber, python-docx, tree-sitter grammars, trafilatura, Pillow, pypdfium2.
  OCR, image descriptions, embeddings, graph extraction and summaries are calls to your providers.
- Scale it with `docker compose up -d --scale worker=3`: jobs are I/O-bound, so provider rate limits matter more
  than CPU.
- Health check: Celery `inspect ping`.
- Limits (archives, images, web pages, graph extraction): `ARCHIVE_*`, `IMAGE_*`, `OCR_MAX_PAGES`, `WEB_*`,
  `GRAPH_*` in `.env`.
