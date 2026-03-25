"""Celery tasks for the github-owners reconciliation.

This module defines background tasks for reconciling GitHub organization
owner membership. Tasks run in Celery workers, separate from the FastAPI app.
"""

from typing import Any

from celery import Task
from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.github import GithubOrgClientFactory
from qontract_api.integrations.github_owners.domain import GithubOrgDesiredState
from qontract_api.integrations.github_owners.schemas import GithubOwnersTaskResult
from qontract_api.integrations.github_owners.service import GithubOwnersService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task, organizations: list[GithubOrgDesiredState], **_: Any
) -> str:
    """Generate lock key for task deduplication.

    Lock key is based on org names to prevent concurrent reconciliations
    for the same organizations.

    Args:
        organizations: List of GithubOrgDesiredState models

    Returns:
        Lock key suffix (sorted org names joined by comma)
    """
    org_names = sorted(org.org_name for org in organizations)
    return ",".join(org_names)


# Use <integration-name>.<task-name> format for task names
# This helps to relate tasks to integrations in dashboards and monitoring
@celery_app.task(bind=True, name="github-owners.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_github_owners_task(
    self: Any,  # Celery Task instance (bind=True)
    organizations: list[GithubOrgDesiredState],
    *,
    dry_run: bool = True,
) -> GithubOwnersTaskResult | dict[str, str]:
    """Reconcile GitHub organization owner membership (background task).

    This task runs in a Celery worker, not in the FastAPI application.
    Uses global cache instance (get_cache()) shared across all tasks in worker.

    Args:
        self: Celery task instance (bind=True)
        organizations: List of GithubOrgDesiredState models (pickle-serialized)
        dry_run: If True, only calculate actions without executing

    Returns:
        GithubOwnersTaskResult on success
        {"status": "skipped", "reason": "duplicate_task"} if duplicate task

    Note:
        @deduplicated_task decorator may return early if duplicate task is detected.
        This prevents concurrent reconciliations for the same orgs.
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        event_manager = get_event_manager()

        github_org_client_factory = GithubOrgClientFactory(
            cache=cache, settings=settings
        )
        service = GithubOwnersService(
            github_org_client_factory=github_org_client_factory,
            secret_manager=secret_manager,
            settings=settings,
        )

        result = service.reconcile(
            organizations=organizations,
            dry_run=dry_run,
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
            # Publish one event per successfully applied action.
            # result.applied_actions excludes actions that failed to execute,
            # preventing spurious success events for partial failures.
            for action in result.applied_actions:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type=f"qontract-api.github-owners.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )

            # Publish one error event per reconciliation error so that failures
            # are visible in the event stream. In non-dry-run mode the client
            # integration does not wait for the task result, so errors would
            # otherwise be silent outside of worker logs.
            for error in result.errors:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.github-owners.error",
                        data={"error": error},
                        datacontenttype="application/json",
                    )
                )

        return result

    except Exception as e:
        logger.exception(f"Task {request_id} failed with error")
        return GithubOwnersTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[str(e)],
        )
