"""Celery application for asynchronous ingestion jobs.

M0 only defines the queues and a `ping` task; ingestion steps are added from M1.
"""

from __future__ import annotations

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
    task_serializer="json",
    accept_content=["json"],
)


@celery_app.task(name="opennotebook.ping")
def ping() -> str:
    return "pong"
