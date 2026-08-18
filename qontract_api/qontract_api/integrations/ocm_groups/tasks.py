"""Celery tasks for OCM groups reconciliation.

This module defines background tasks for reconciling OCM cluster group
memberships. Tasks run in Celery workers, separate from the FastAPI application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.ocm_groups.schemas import OcmGroupsTaskResult
from qontract_api.integrations.ocm_groups.service import OcmGroupsService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.ocm_groups.domain import (
        OcmGroupsCluster,
        OcmGroupUser,
    )
    from qontract_api.ocm.domain import OcmConnectionParams

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task,
    ocm_environment: str,
    ocm_connection: OcmConnectionParams,
    **_: Any,
) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on OCM environment to prevent concurrent
    reconciliations for the same OCM environment.
    """
    return f"ocm-groups:{ocm_environment}:{ocm_connection.ocm_url}"


@celery_app.task(bind=True, name="ocm-groups.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_ocm_groups_task(
    self: Any,  # Celery Task instance (bind=True)
    ocm_environment: str,
    ocm_connection: OcmConnectionParams,
    clusters: list[OcmGroupsCluster],
    desired_state: list[OcmGroupUser],
    *,
    dry_run: bool = True,
) -> OcmGroupsTaskResult:
    """Reconcile OCM cluster group memberships (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = OcmGroupsService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            ocm_environment=ocm_environment,
            ocm_connection=ocm_connection,
            clusters=clusters,
            desired_state=desired_state,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return OcmGroupsTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=result.applied_count,
        errors=result.errors,
    )

    if not dry_run and event_manager:
        try:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.ocm-groups.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.ocm-groups.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
