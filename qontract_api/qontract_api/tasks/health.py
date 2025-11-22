"""Health check tasks for Celery worker."""

from qontract_api.tasks import celery_app


@celery_app.task
def health_check() -> dict[str, str]:
    """Simple health check task to verify Celery worker is operational."""
    return {
        "status": "healthy",
        "message": "Celery worker is operational",
    }
