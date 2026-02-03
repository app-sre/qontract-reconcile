"""Celery tasks for qontract-api."""

from datetime import UTC, datetime
from typing import Any

import celery
import structlog
from celery import Celery
from prometheus_client import Counter, Histogram

from qontract_api.config import settings
from qontract_api.logger import get_logger, setup_logger, setup_logging
from qontract_api.models import TaskResult
from qontract_api.tasks._deduplication import deduplicated_task
from qontract_api.tasks._utils import (
    BackgroundTask,
    get_celery_task_result,
    wait_for_task_completion,
)

logger = structlog.getLogger(__name__)

task_elapsed_time = Histogram(
    name="qontract_reconcile_worker_task_elapsed_seconds",
    documentation="Total elapsed seconds for worker tasks. Includes queue time.",
    labelnames=["name", "status"],
)
task_execution_elapsed_time = Histogram(
    name="qontract_reconcile_worker_task_execution_elapsed_seconds",
    documentation="Elapsed seconds for worker task execution. Excludes queue time.",
    labelnames=["name", "status"],
)
task_success_count = Counter(
    name="qontract_reconcile_worker_task_success_total",
    documentation="Total number of successful worker task.",
    labelnames=["name"],
)
task_failure_count = Counter(
    name="qontract_reconcile_worker_task_failure_total",
    documentation="Total number of failed worker task.",
    labelnames=["name"],
)
task_applied_actions_count = Counter(
    name="qontract_reconcile_worker_task_applied_actions_total",
    documentation="Total number of applied actions by worker tasks.",
    labelnames=["name"],
)


@celery.signals.setup_logging.connect
def setup_loggers(*_: Any, **__: Any) -> None:
    """Setup Celery logger to use application logging configuration."""
    setup_logging()


@celery.signals.before_task_publish.connect
def on_before_task_publish(headers: dict, *_: tuple, **__: dict) -> None:
    """Setup all necessary context before task is published.

    This method is executed in the producer process just before
    the task is sent to the broker.
    """
    context = structlog.contextvars.get_merged_contextvars(logger)
    headers["__structlog_context__"] = context
    # the task is scheduled for later, so, let's start the countdown from then
    publish_time = (
        datetime.fromisoformat(headers.get("eta", ""))
        if headers.get("eta")
        else datetime.now(tz=UTC)
    )
    headers["__publish_time"] = publish_time.isoformat()


@celery.signals.task_prerun.connect
def on_task_prerun(task: celery.Task, *_: tuple, **__: dict) -> None:
    """Setup all necessary context before task is run.

    This method is executed in the worker process just before
    the task is executed.
    """
    # clear previous contextvars
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_name=task.name)
    metadata = getattr(task.request, "__structlog_context__", {})
    structlog.contextvars.bind_contextvars(**metadata)
    setattr(task.request, "__prerun_time", datetime.now(tz=UTC).isoformat())


@celery.signals.task_postrun.connect
def on_task_postrun(
    task: celery.Task, state: str, retval: Any, *_: tuple, **__: dict
) -> None:
    """Finalize task execution and calculate statistics."""
    now = datetime.now(tz=UTC)

    if publish_time_str := getattr(task.request, "__publish_time", None):
        publish_time = datetime.fromisoformat(publish_time_str)
        task_elapsed_time.labels(name=task.name, status=state).observe(
            amount=(now - publish_time).total_seconds()
        )

    if prerun_time_str := getattr(task.request, "__prerun_time", None):
        prerun_time = datetime.fromisoformat(prerun_time_str)
        task_execution_elapsed_time.labels(name=task.name, status=state).observe(
            amount=(now - prerun_time).total_seconds()
        )

    if isinstance(retval, TaskResult):
        if retval.errors:
            task_failure_count.labels(name=task.name).inc()
        else:
            task_success_count.labels(name=task.name).inc()

        task_applied_actions_count.labels(name=task.name).inc(retval.applied_count)


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
