"""Celery tasks for Glitchtip project alerts reconciliation.

This module defines background tasks for reconciling Glitchtip project alerts.
Tasks run in Celery workers, separate from the FastAPI application.
"""

from typing import Any

from celery import Task

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.integrations.glitchtip_project_alerts.glitchtip_client_factory import (
    GlitchtipClientFactory,
)
from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipInstance,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.integrations.glitchtip_project_alerts.service import (
    GlitchtipProjectAlertsService,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

logger = get_logger(__name__)


def generate_lock_key(_self: Task, instances: list[GlitchtipInstance], **_: Any) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on instance names to prevent concurrent reconciliations
    for the same instances.

    Args:
        instances: List of GlitchtipInstance models

    Returns:
        Lock key suffix (instance names joined by comma)
    """
    instance_names = sorted(inst.name for inst in instances)
    return ",".join(instance_names)


# Use <integration-name>.<task-name> format for task names
# This helps to relate tasks to integrations in the dashboards and monitoring
@celery_app.task(bind=True, name="glitchtip-project-alerts.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_glitchtip_project_alerts_task(
    self: Any,  # Celery Task instance (bind=True)
    instances: list[GlitchtipInstance],
    *,
    dry_run: bool = True,
) -> GlitchtipProjectAlertsTaskResult | dict[str, str]:
    """Reconcile Glitchtip project alerts (background task).

    This task runs in a Celery worker, not in the FastAPI application.
    Uses global cache instance (get_cache()) shared across all tasks in worker.

    Args:
        self: Celery task instance (bind=True)
        instances: List of GlitchtipInstance models (pickle-serialized by Celery)
        dry_run: If True, only calculate actions without executing

    Returns:
        GlitchtipProjectAlertsTaskResult on success
        {"status": "skipped", "reason": "duplicate_task"} if duplicate task

    Note:
        @deduplicated_task decorator may return early if duplicate task is detected.
        This prevents concurrent reconciliations for the same instances.
    """
    request_id = self.request.id

    try:
        # Get shared dependencies
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)

        # Create factory and service
        glitchtip_client_factory = GlitchtipClientFactory(
            cache=cache, settings=settings
        )
        service = GlitchtipProjectAlertsService(
            glitchtip_client_factory=glitchtip_client_factory,
            secret_manager=secret_manager,
            settings=settings,
        )

        # Execute reconciliation
        result = service.reconcile(
            instances=instances,
            dry_run=dry_run,
        )

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            actions=[action.model_dump() for action in result.actions],
            errors=result.errors,
        )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return GlitchtipProjectAlertsTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[str(e)],
        )
