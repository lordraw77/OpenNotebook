"""Enqueueing of background jobs. Kept tiny so API tests can replace it."""

from __future__ import annotations

import uuid


def _send(name: str, args: list, queue: str) -> None:
    from opennotebook.worker import celery_app

    celery_app.send_task(name, args=args, queue=queue)


def enqueue_ingestion(source_id: uuid.UUID, reason: str = "upload") -> None:
    _send("opennotebook.ingest_source", [str(source_id), reason], "parse")


def enqueue_purge(source_id: uuid.UUID) -> None:
    _send("opennotebook.purge_source", [str(source_id)], "default")


def enqueue_refresh_ancestors(node_id: uuid.UUID) -> None:
    _send("opennotebook.refresh_ancestors", [str(node_id)], "default")


def enqueue_summary(source_id: uuid.UUID) -> None:
    _send("opennotebook.summarize_source", [str(source_id)], "summary")
