# Service Level Objectives

Objectives for one instance (NFR-02, NFR-03, NFR-04: 10–50 users, up to 1M chunks). They exclude the
time spent inside model providers beyond what is stated, since providers are external.

| SLO | Objective | Measured by (Prometheus) | Alert |
|---|---|---|---|
| Availability | 99.5% of API requests answered without a server error (5xx), over 30 days | `1 - rate(opennotebook_http_requests_total{status=~"5.."}) / rate(opennotebook_http_requests_total)` | `OpenNotebookHighErrorRate` (> 5% for 10 min), `OpenNotebookApiDown` |
| Chat responsiveness | p95 time to first token < 3 s with a fast chat provider (Groq, Cerebras), < 8 s in general | `histogram_quantile(0.95, opennotebook_chat_time_to_first_token_seconds_bucket{mode="chat"})` | `OpenNotebookChatSlow` (p95 > 8 s for 30 min) |
| Search latency | p95 < 1.5 s for `POST /api/search` (includes the query embedding call) | `opennotebook_http_request_duration_seconds_bucket{route="/api/search"}` | dashboard |
| Ingestion throughput | ≥ 20 text-PDF pages per minute per worker, excluding provider latency | `opennotebook_ingestion_duration_seconds`, load test | `OpenNotebookQueueBacklog` (> 100 jobs for 30 min) |
| Ingestion reliability | < 1% of sources fail for reasons other than unsupported content or provider outages | `opennotebook_ingestion_jobs_total{status="failed"}` | `OpenNotebookIngestionFailures` |
| Isolation (NFR-05) | 0 passages from unauthorized scopes, ever | automated tests (ACL, groups, graph, research) on every change | CI |
| Answer quality | on `eval/`: recall@5 ≥ 0.9, citation accuracy ≥ 0.9, out-of-domain abstention ≥ 0.95 | `scripts/rag_eval.py` (manual or scheduled) | review after model changes |

Error budget: 0.5% of requests per 30 days (≈ 3.6 hours of full outage). When the budget is spent, changes
other than fixes wait until it recovers.

Measured values: [performance.md](performance.md) and [rag-evaluation.md](rag-evaluation.md).
