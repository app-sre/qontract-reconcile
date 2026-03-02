"""Celery tasks for Slack usergroups reconciliation.

This module defines background tasks for reconciling Slack usergroups.
Tasks run in Celery workers, separate from the FastAPI application.
"""

from typing import Any

from celery import Task
from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroupsTaskResult,
    SlackWorkspace,
)
from qontract_api.integrations.slack_usergroups.service import SlackUsergroupsService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

logger = get_logger(__name__)


def generate_lock_key(_self: Task, workspaces: list[SlackWorkspace], **_: Any) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on workspace names to prevent concurrent reconciliations
    for the same workspaces.

    Args:
        workspaces: List of workspace dictionaries (serialized SlackWorkspace models)

    Returns:w
        Lock key suffix (workspace names joined by comma)
    """
    workspace_names = sorted(ws.name for ws in workspaces)
    return ",".join(workspace_names)


# Use <integration-name>.<task-name> format for task names
# This helps to relate tasks to integrations in the dahsboards and monitoring
@celery_app.task(bind=True, name="slack-usergroups.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_slack_usergroups_task(
    self: Any,  # Celery Task instance (bind=True)
    workspaces: list[SlackWorkspace],
    *,
    dry_run: bool = True,
) -> SlackUsergroupsTaskResult | dict[str, str]:
    """Reconcile Slack usergroups (background task).

    This task runs in a Celery worker, not in the FastAPI application.
    Uses global cache instance (get_cache()) shared across all tasks in worker.

    Args:
        self: Celery task instance (bind=True)
        workspaces: List of SlackWorkspace models (pickle-serialized by Celery)
        dry_run: If True, only calculate actions without executing

    Returns:
        SlackUsergroupsTaskResult on success
        {"status": "skipped", "reason": "duplicate_task"} if duplicate task

    Note:
        @deduplicated_task decorator may return early if duplicate task is detected.
        This prevents concurrent reconciliations for the same workspaces.
    """
    request_id = self.request.id

    try:
        # Get shared dependencies
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        # Create service
        service = SlackUsergroupsService(
            cache=cache,
            secret_manager=secret_manager,
            settings=settings,
        )

        # Execute reconciliation
        result = service.reconcile(
            workspaces=workspaces,
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

        # Publish events for applied actions (non-dry-run only)
        if not dry_run and result.applied_count > 0 and event_manager:
            for action in result.actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.slack-usergroups.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return SlackUsergroupsTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[str(e)],
        )
