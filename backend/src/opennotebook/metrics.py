"""Prometheus metrics of the application (in addition to the HTTP metrics of main.py).

The api exposes them on /metrics (internal network only). Worker processes (Celery prefork children) write
them in multiprocess mode; the worker's main process serves them on WORKER_METRICS_PORT (see cli.cmd_worker).
Label values are bounded: provider names, phases, statuses and modes, never ids or user input.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

_SECONDS = (0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5, 10, 20, 30, 60, 120, 300)

PROVIDER_CALLS = Counter(
    "opennotebook_provider_calls_total",
    "Model calls to external providers",
    ["provider", "phase", "outcome"],  # outcome: ok | error
)
PROVIDER_LATENCY = Histogram(
    "opennotebook_provider_call_duration_seconds",
    "Duration of successful model calls (streams: until the first token)",
    ["provider", "phase"],
    buckets=_SECONDS,
)
INGESTION_JOBS = Counter("opennotebook_ingestion_jobs_total", "Finished ingestion jobs", ["kind", "status"])
INGESTION_DURATION = Histogram(
    "opennotebook_ingestion_duration_seconds", "Ingestion job duration", ["kind"], buckets=_SECONDS
)
BACKGROUND_TASKS = Counter(
    "opennotebook_background_tasks_total",
    "Summary and graph extraction jobs",
    ["task", "outcome"],  # outcome: done | skipped | failed | retry
)
CHAT_FIRST_TOKEN = Histogram(
    "opennotebook_chat_time_to_first_token_seconds",
    "Time from the question to the first answer token (includes retrieval and provider latency)",
    ["mode"],
    buckets=_SECONDS,
)
CHAT_ANSWERS = Counter("opennotebook_chat_answers_total", "Chat answers", ["mode", "status"])
RETRIEVAL_DURATION = Histogram(
    "opennotebook_retrieval_duration_seconds", "Hybrid retrieval (search, rerank, graph)", buckets=_SECONDS
)
# Updated periodically by the api (see main.py)
QUEUE_DEPTH = Gauge(
    "opennotebook_queue_depth", "Jobs waiting in a worker queue", ["queue"], multiprocess_mode="max"
)
SOURCES = Gauge("opennotebook_sources", "Sources by ingestion status", ["status"], multiprocess_mode="max")


def provider_label(label: str) -> str:
    """'groq/openai/gpt-oss-120b' -> 'groq' (the provider name, bounded cardinality)."""
    return label.split("/", 1)[0]


@contextmanager
def timed(histogram: Histogram, *labels: str) -> Iterator[None]:
    start = time.perf_counter()
    try:
        yield
    finally:
        (histogram.labels(*labels) if labels else histogram).observe(time.perf_counter() - start)
