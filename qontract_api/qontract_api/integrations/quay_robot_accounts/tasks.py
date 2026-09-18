"""Celery tasks for quay-robot-accounts reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotAccountsErrorEvent,
    QuayRobotAccountsTaskResult,
)
from qontract_api.integrations.quay_robot_accounts.service import (
    QuayRobotAccountsService,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.quay_robot_accounts.domain import QuayOrgDesiredState

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task, organizations: list[QuayOrgDesiredState], **_: Any
) -> str:
    """Lock key from sorted instance/org identifiers."""
    org_keys = sorted(f"{org.instance_name}/{org.org_name}" for org in organizations)
    return ",".join(org_keys)


@celery_app.task(bind=True, name="quay-robot-accounts.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_quay_robot_accounts_task(
    self: Any,
    organizations: list[QuayOrgDesiredState],
    *,
    dry_run: bool = True,
) -> QuayRobotAccountsTaskResult:
    """Reconcile Quay robot accounts (background task)."""
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        service = QuayRobotAccountsService(
            secret_manager=secret_manager,
            cache=cache,
            settings=settings,
        )

        result = service.reconcile(
            organizations=organizations,
            dry_run=dry_run,
        )
    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return QuayRobotAccountsTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )

    logger.info(
        f"Task {request_id} completed",
        status=result.status,
        total_actions=len(result.actions),
        applied_count=len(result.applied_actions),
        actions=[action.model_dump() for action in result.actions],
        errors=result.errors,
    )

    if not dry_run and event_manager:
        try:
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.quay-robot-accounts.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.quay-robot-accounts.error",
                        data=QuayRobotAccountsErrorEvent(error=error).model_dump(
                            mode="json"
                        ),
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
