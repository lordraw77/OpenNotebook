# Performance

Measured with `scripts/loadtest.py` on the development test host (4 vCPU, 7.5 GB RAM, one api process, one
worker container with 4 processes, PostgreSQL/Qdrant/SeaweedFS on the same host), 2026-11-09, version 0.5.1.

```bash
ON_URL=http://<host>:8080 ON_EMAIL=<admin> ON_PASSWORD=... uv run --project backend python scripts/loadtest.py \
  --users 10 --seconds 45 --chats 8 --pdf-pages 60 \
  --embedding cloudflare/@cf/baai/bge-m3 --chat groq/openai/gpt-oss-20b
```

The script creates a temporary project and users (left deactivated afterwards), uploads `eval/corpus`, runs
the load and deletes the project. `--embedding` / `--chat` set the models for that project only.

## Results with fast providers (Cloudflare embeddings, Groq chat)

| Measure | Result | SLO |
|---|---|---|
| Search, 10 users × 45 s (0.5 s think time) | 482 requests, all 200; 10.3 req/s; p50 0.20 s, p95 0.52 s, p99 10.2 s | p95 < 1.5 s ✅ |
| Chat, retrieval (question → passages) | p50 0.36 s, p95 0.76 s | — |
| Chat, time to first token | p50 1.33 s, p95 2.10 s | p95 < 3 s with a fast provider ✅ |
| Ingestion, 60-page text PDF (71 chunks) | 34.5 s → 104 pages/min per worker | ≥ 20 pages/min ✅ |

The search p99 comes from the provider: 2 of 509 Cloudflare embedding calls took 10–20 s (99% under 0.86 s).
Interactive searches cap the provider wait at `SEARCH_TIMEOUT_S`.

## Results with a slow embedding provider (CPU-only Ollama on the LAN)

Same test with the project on `ollama/bge-m3` and chat on NVIDIA `nemotron-3-ultra`: search p50 1.13 s /
p95 2.53 s (the query embedding alone: p50 0.9 s, p95 2.9 s), chat first token p95 14 s, ingestion
9.4 pages/min (all of it waiting for embeddings). Latency follows the providers: pick fast models for the
`embedding` and `chat` phases (per project if needed); RAG Status and the provider latency panel show which
one is slow.

## Capacity notes

- The api is I/O-bound (database, Qdrant, providers): one process served 10 req/s of searches with p95 0.5 s.
- Ingestion scales with worker replicas (`docker compose up -d --scale worker=N`); each replica runs one
  process per CPU. Graph extraction and summaries share the workers: with slow LLMs they can delay
  ingestion of new sources. Watch `opennotebook_queue_depth`.
- Rate limits per user (`CHAT_RATE_LIMIT_PER_MINUTE`, `SEARCH_RATE_LIMIT_PER_MINUTE`,
  `RESEARCH_RATE_LIMIT_PER_HOUR`) protect provider quotas; raise them for automation accounts if needed.
