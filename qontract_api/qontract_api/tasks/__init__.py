"""Celery tasks for qontract-api."""

from celery import Celery

from qontract_api.config import settings

# Create Celery app
celery_app = Celery(
    "qontract_api",
    broker=settings.get_celery_broker_url(),
    backend=settings.get_celery_result_backend(),
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Import tasks to register them
from qontract_api.tasks import health  # noqa: E402, F401

__all__ = ["celery_app"]
