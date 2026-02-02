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

logger = structlog.getLogger(__name__)


@celery.signals.setup_logging.connect
def setup_loggers(*_: Any, **__: Any) -> None:
    """Setup Celery logger to use application logging configuration."""
    setup_logging()


@celery.signals.task_prerun.connect
def on_task_prerun(task: celery.Task, *_: tuple, **__: dict) -> None:
    # clear previous contextvars
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_name=task.name)
    metadata = getattr(task.request, "__structlog_context__", {})
    structlog.contextvars.bind_contextvars(**metadata)


@celery.signals.before_task_publish.connect
def on_before_task_publish(headers: dict, *_: tuple, **__: dict) -> None:
    context = structlog.contextvars.get_merged_contextvars(logger)
    headers["__structlog_context__"] = context


# Create Celery app
celery_app = Celery(
    "qontract_api",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend(),
    broker_connection_retry_on_startup=True,
    worker_enable_remote_control=False,
    worker_hijack_root_logger=False,
    task_cls=BackgroundTask,
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
