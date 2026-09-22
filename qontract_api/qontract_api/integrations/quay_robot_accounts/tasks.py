"""Celery tasks for quay-robot-accounts reconciliation."""

from __future__ import annotations

from contextlib import ExitStack
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

    from qontract_api.cache import CacheBackend
    from qontract_api.integrations.quay_robot_accounts.domain import QuayOrgDesiredState

logger = get_logger(__name__)

_TASK_LOCK_TIMEOUT_SECONDS = 600
_ORG_LOCK_KEY_PREFIX = "quay-robot-accounts:"


def org_identifier(org: QuayOrgDesiredState) -> str:
    """Return the canonical organization identifier (`instance/org`)."""
    return f"{org.instance_name}/{org.org_name}"


def org_lock_key(org: QuayOrgDesiredState) -> str:
    """Return the per-organization lock key shared by overlapping tasks."""
    return f"{_ORG_LOCK_KEY_PREFIX}{org_identifier(org)}"


def generate_lock_key(
    _self: Task, organizations: list[QuayOrgDesiredState], **_: Any
) -> str:
    """Skip identical payloads. Overlapping org sets share org_lock_key()."""
    return ",".join(sorted(org_identifier(org) for org in organizations))


def _reconcile_with_org_locks(
    cache: CacheBackend,
    service: QuayRobotAccountsService,
    organizations: list[QuayOrgDesiredState],
    *,
    dry_run: bool,
) -> QuayRobotAccountsTaskResult:
    """Hold per-org locks across read, diff, and Quay mutations."""
    with ExitStack() as stack:
        for key in sorted({org_lock_key(org) for org in organizations}):
            stack.enter_context(cache.lock(key, timeout=_TASK_LOCK_TIMEOUT_SECONDS))
        return service.reconcile(organizations=organizations, dry_run=dry_run)


@celery_app.task(bind=True, name="quay-robot-accounts.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=_TASK_LOCK_TIMEOUT_SECONDS)
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

        result = _reconcile_with_org_locks(
            cache,
            service,
            organizations,
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
