# Monitoring

Start the `observability` profile (Prometheus, Grafana, Jaeger) and, for traces, set
`OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4318` in `.env`:

```bash
docker compose --profile observability up -d     # deployment directory
# or COMPOSE_PROFILES=observability in .env
```

| Tool | Address (default bind 127.0.0.1) | Content |
|---|---|---|
| Grafana | `:3000` (admin / `GRAFANA_ADMIN_PASSWORD`) | dashboard **OpenNotebook overview** (folder OpenNotebook); Prometheus and Jaeger data sources |
| Prometheus | `:9090` | metrics of the api (`api:8000/metrics`) and of every worker replica (`worker:9101`, DNS discovery); alert rules |
| Jaeger | `:16686` | traces of `opennotebook-api` and `opennotebook-worker` |

## Metrics

| Metric | Labels | Meaning |
|---|---|---|
| `opennotebook_http_requests_total`, `opennotebook_http_request_duration_seconds` | method, route, status | API traffic and latency |
| `opennotebook_chat_time_to_first_token_seconds` | mode | question → first answer token (retrieval + provider) |
| `opennotebook_chat_answers_total` | mode, status (complete, error, stopped, abstained) | chat outcomes |
| `opennotebook_retrieval_duration_seconds` | | hybrid search + rerank + graph expansion |
| `opennotebook_provider_calls_total`, `opennotebook_provider_call_duration_seconds` | provider, phase, outcome | every model call (streams: until the first token) |
| `opennotebook_ingestion_jobs_total`, `opennotebook_ingestion_duration_seconds` | kind, status | ingestion jobs (worker) |
| `opennotebook_background_tasks_total` | task (summary, graph), outcome | summaries and graph extraction (worker) |
| `opennotebook_queue_depth` | queue | jobs waiting per worker queue (updated every 30 s) |
| `opennotebook_sources` | status | sources by status (updated every 30 s) |

Labels never contain ids, prompts or user input. `/metrics` is served on the internal network only (nginx does
not proxy it).

## Alerts

Rules in `deploy/compose/observability/alerts.yml` (inlined in the deployment Compose file by
`make sync-deploy`): api down, worker down, error rate, slow chat, provider errors, queue backlog, ingestion
failures. Each has a `runbook` annotation pointing to [runbooks.md](runbooks.md). Prometheus evaluates them;
route them to e-mail or chat with an Alertmanager or with Grafana alerting (not bundled).

## Logs

All services log JSON lines to stdout (request id, route, status, duration; never prompts, documents or keys).
Docker rotates them (20 MB × 5 per container in the deployment Compose file): `docker compose logs -f api worker`.
Ship them to a central store with your usual Docker logging driver if needed.

## Traces

With `OTEL_EXPORTER_OTLP_ENDPOINT` set, spans cover incoming HTTP requests (FastAPI), outgoing HTTP (model
providers, Qdrant, web fetches) and Celery tasks. Database spans are not recorded yet (the SQLAlchemy
instrumentation does not support SQLAlchemy 2.1). Any OTLP/HTTP backend works; Jaeger keeps traces in memory
(they are lost on restart).
