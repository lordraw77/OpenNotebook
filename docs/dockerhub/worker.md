This image runs the **ingestion worker** (Celery): it parses uploaded files and archives, transcribes images and
scanned pages through OCR/vision providers, fetches web pages (SSRF-protected), computes embeddings, extracts the
knowledge graph and writes summaries and suggested questions.
