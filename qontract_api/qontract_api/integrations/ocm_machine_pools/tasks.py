"""Celery tasks for OCM machine pool reconciliation.

This module defines background tasks for reconciling OCM machine pools and
node pools. Tasks run in Celery workers, separate from the FastAPI application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.ocm_machine_pools.schemas import (
    OcmMachinePoolsTaskResult,
)
from qontract_api.integrations.ocm_machine_pools.service import OcmMachinePoolsService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.ocm_machine_pools.domain import (
        DesiredClusterMachinePools,
    )
    from qontract_api.ocm.domain import OcmConnectionParams

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task,
    ocm_environment: str,
    ocm_connection: OcmConnectionParams,
    *_args: Any,
    **_kwargs: Any,
) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on OCM environment to prevent concurrent
    reconciliations for the same OCM environment.
    """
    return f"ocm-machine-pools:{ocm_environment}:{ocm_connection.ocm_url}"


@celery_app.task(bind=True, name="ocm-machine-pools.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_ocm_machine_pools_task(
    self: Any,  # Celery Task instance (bind=True)
    ocm_environment: str,
    ocm_connection: OcmConnectionParams,
    clusters: list[DesiredClusterMachinePools],
    *,
    dry_run: bool = True,
) -> OcmMachinePoolsTaskResult:
    """Reconcile OCM machine/node pools (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = OcmMachinePoolsService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            ocm_environment=ocm_environment,
            ocm_connection=ocm_connection,
            clusters=clusters,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return OcmMachinePoolsTaskResult(
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
                        type=f"qontract-api.ocm-machine-pools.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.ocm-machine-pools.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
