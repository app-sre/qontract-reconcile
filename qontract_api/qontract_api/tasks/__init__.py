"""Celery tasks for qontract-api."""

from typing import Any

import celery
import structlog
from celery import Celery

from qontract_api.config import settings
from qontract_api.logger import get_logger, setup_logger, setup_logging
from qontract_api.tasks._deduplication import deduplicated_task
from qontract_api.tasks._utils import (
    BackgroundTask,
    get_celery_task_result,
    wait_for_task_completion,
)


@celery.signals.setup_logging.connect
def setup_loggers(*_: Any, **__: Any) -> None:
    """Setup Celery logger to use application logging configuration."""
    setup_logging()


@celery.signals.task_prerun.connect
def on_task_prerun(task_id: str, task: celery.Task, *_: Any, **__: Any) -> None:
    structlog.contextvars.bind_contextvars(request_id=task_id, task_name=task.name)


# Create Celery app
celery_app = Celery(
    "qontract_api",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend(),
    broker_connection_retry_on_startup=True,
    worker_enable_remote_control=False,
    worker_hijack_root_logger=False,
    timezone="UTC",
    # support pydantic models
    task_serializer="pickle",
    result_serializer="pickle",
    event_serializer="json",
    accept_content=["application/json", "application/x-python-serialize"],
    result_accept_content=["application/json", "application/x-python-serialize"],
    include=[
        "qontract_api.tasks.health",
        "qontract_api.integrations.slack_usergroups.tasks",
    ],
)


__all__ = [
    "BackgroundTask",
    "celery_app",
    "deduplicated_task",
    "get_celery_task_result",
    "get_logger",
    "setup_logger",
    "wait_for_task_completion",
]
