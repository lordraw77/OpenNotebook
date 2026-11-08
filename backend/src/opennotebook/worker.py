"""Celery application for asynchronous ingestion jobs.

Each worker process keeps one asyncio event loop, so the async database engine and the Qdrant client
(both bound to a loop) are reused across tasks.
"""

from __future__ import annotations

import asyncio
import os
import uuid

from celery import Celery
from kombu import Queue

from opennotebook.config import get_settings
from opennotebook.logging_setup import configure_logging

QUEUES = ("default", "parse", "ocr_vision", "embed", "graph", "summary")

settings = get_settings()
configure_logging(settings.log_level)

celery_app = Celery("opennotebook", broker=settings.redis_url_with_auth, backend=settings.redis_url_with_auth)
celery_app.conf.update(
    task_queues=[Queue(q) for q in QUEUES],
    task_default_queue="default",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    worker_hijack_root_logger=False,
    broker_connection_retry_on_startup=True,
    result_expires=3600,
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
)

_loop: asyncio.AbstractEventLoop | None = None
_loop_pid: int | None = None


def run(coro):  # type: ignore[no-untyped-def]
    """Run a coroutine on this process's persistent event loop."""
    global _loop, _loop_pid
    if _loop is None or _loop_pid != os.getpid():
        _loop = asyncio.new_event_loop()
        _loop_pid = os.getpid()
        asyncio.set_event_loop(_loop)
    return _loop.run_until_complete(coro)


def _deps():  # type: ignore[no-untyped-def]
    from opennotebook.db import get_sessionmaker
    from opennotebook.ingestion.vectors import get_vector_index
    from opennotebook.storage import get_blob_store

    return get_sessionmaker(), get_blob_store(), get_vector_index()


@celery_app.task(name="opennotebook.ping")
def ping() -> str:
    return "pong"


@celery_app.task(name="opennotebook.ingest_source", bind=True, acks_late=True)
def ingest_source_task(self, source_id: str, reason: str = "upload") -> str:  # type: ignore[no-untyped-def]
    from opennotebook.ingestion.pipeline import RetryableError, ingest_source, mark_failed_after_retries

    sessionmaker, store, index = _deps()
    attempt = self.request.retries + 1

    async def go() -> str:
        async with sessionmaker() as session:
            status = await ingest_source(
                session, uuid.UUID(source_id), store=store, index=index, reason=reason, attempt=attempt
            )
            return status.value

    try:
        return run(go())
    except RetryableError as exc:
        if self.request.retries >= settings.ingestion_max_attempts - 1:
            message = str(exc)

            async def give_up() -> None:
                async with sessionmaker() as session:
                    await mark_failed_after_retries(session, uuid.UUID(source_id), message)

            run(give_up())
            return "failed"
        raise self.retry(exc=exc, countdown=min(600, 30 * 2**self.request.retries)) from exc


@celery_app.task(name="opennotebook.purge_source")
def purge_source_task(source_id: str) -> None:
    from opennotebook.ingestion.pipeline import purge_source

    sessionmaker, store, index = _deps()

    async def go() -> None:
        async with sessionmaker() as session:
            await purge_source(session, uuid.UUID(source_id), store=store, index=index)

    run(go())


@celery_app.task(name="opennotebook.refresh_ancestors")
def refresh_ancestors_task(node_id: str) -> int:
    from opennotebook.ingestion.pipeline import refresh_ancestors

    sessionmaker, _, index = _deps()

    async def go() -> int:
        async with sessionmaker() as session:
            return await refresh_ancestors(session, uuid.UUID(node_id), index=index)

    return run(go())
