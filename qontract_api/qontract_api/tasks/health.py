"""Health check tasks for Celery worker."""

from typing import Any

from qontract_api.health import HealthStatus
from qontract_api.logger import get_logger
from qontract_api.tasks import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True)
def health_check(_: Any) -> HealthStatus:
    """Simple health check task to verify Celery worker is operational."""
    return HealthStatus(status="healthy", message="Celery worker is operational")
