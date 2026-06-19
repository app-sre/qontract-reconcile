"""Celery tasks for Glitchtip reconciliation."""

from typing import Any

from celery import Task
from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.glitchtip import GlitchtipClientFactory
from qontract_api.integrations.glitchtip.domain import GIInstance
from qontract_api.integrations.glitchtip.schemas import GlitchtipTaskResult
from qontract_api.integrations.glitchtip.service import GlitchtipService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

logger = get_logger(__name__)


def generate_lock_key(_self: Task, instances: list[GIInstance], **_: Any) -> str:
    """Generate deduplication lock key based on instance names."""
    instance_names = sorted(inst.name for inst in instances)
    return ",".join(instance_names)


@celery_app.task(bind=True, name="glitchtip.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_glitchtip_task(
    self: Any,
    instances: list[GIInstance],
    *,
    dry_run: bool = True,
) -> GlitchtipTaskResult:
    """Reconcile Glitchtip organizations, teams, projects, and users (background task).

    Args:
        self: Celery task instance (bind=True)
        instances: List of GlitchtipInstance models
        dry_run: If True, only calculate actions without executing

    Returns:
        GlitchtipTaskResult on success, or with SKIPPED status if duplicate task
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        glitchtip_client_factory = GlitchtipClientFactory(
            cache=cache, settings=settings
        )
        service = GlitchtipService(
            glitchtip_client_factory=glitchtip_client_factory,
            secret_manager=secret_manager,
            settings=settings,
        )

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

        if not dry_run and event_manager:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.glitchtip.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )

            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.glitchtip.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return GlitchtipTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[str(e)],
        )
