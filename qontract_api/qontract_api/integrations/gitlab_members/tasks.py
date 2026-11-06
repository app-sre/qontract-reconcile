"""Celery tasks for GitLab members reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_utils.events import Event

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.event_manager import get_event_manager
from qontract_api.integrations.gitlab_members.schemas import (
    GitlabMembersErrorEvent,
    GitlabMembersTaskResult,
)
from qontract_api.integrations.gitlab_members.service import GitlabMembersService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

    from qontract_api.integrations.gitlab_members.domain import (
        GitlabMembersInstanceConfig,
    )

logger = get_logger(__name__)


def generate_lock_key(
    _self: Task, instances: list[GitlabMembersInstanceConfig], **_: Any
) -> str:
    """Deduplicate tasks by sorted instance names."""
    return ",".join(sorted(instance.lock_key() for instance in instances))


@celery_app.task(bind=True, name="gitlab-members.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_gitlab_members_task(
    self: Any,
    instances: list[GitlabMembersInstanceConfig],
    *,
    dry_run: bool = True,
) -> GitlabMembersTaskResult:
    """Reconcile GitLab group membership (background task).

    Args:
        self: Celery task instance (bind=True)
        instances: List of GitlabMembersInstanceConfig models
        dry_run: If True, only calculate actions without executing
    """
    request_id = self.request.id

    try:
        event_manager = get_event_manager()
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = GitlabMembersService(
            secret_manager=secret_manager,
            cache=cache,
            settings=settings,
        )

        result = service.reconcile(instances=instances, dry_run=dry_run)

    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return GitlabMembersTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected error: {err}"],
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
                        type=f"qontract-api.gitlab-members.{action.action_type}",
                        data=action.model_dump(mode="json"),
                        datacontenttype="application/json",
                    )
                )
            for error in result.errors or []:
                event_manager.publish_event(
                    Event(
                        source=__name__,
                        type="qontract-api.gitlab-members.error",
                        data=GitlabMembersErrorEvent(error=error).model_dump(
                            mode="json"
                        ),
                        datacontenttype="application/json",
                    )
                )
        except Exception:
            logger.exception(f"Task {request_id} failed to publish events")

    return result
