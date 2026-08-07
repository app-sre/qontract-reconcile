"""Celery tasks for Quay repos reconciliation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from qontract_api.cache.factory import get_cache
from qontract_api.integrations.quay_repos.schemas import (
    QuayOrgConfig,
    QuayReposTaskResult,
)
from qontract_api.integrations.quay_repos.service import QuayReposService
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.tasks import celery_app, deduplicated_task

if TYPE_CHECKING:
    from celery import Task

logger = get_logger(__name__)


def generate_lock_key(_self: Task, orgs: list[QuayOrgConfig], **_: Any) -> str:
    """Deduplicate tasks by sorted org keys."""
    return ",".join(sorted(org.key.lock_key() for org in orgs))


@celery_app.task(bind=True, name="quay-repos.reconcile", acks_late=True)
@deduplicated_task(lock_key_fn=generate_lock_key, timeout=600)
def reconcile_quay_repos_task(
    self: Any,
    orgs: list[QuayOrgConfig],
    *,
    dry_run: bool = True,
) -> QuayReposTaskResult:
    """Reconcile Quay repositories (background task).

    Args:
        self: Celery task instance (bind=True)
        orgs: List of QuayOrgConfig models
        dry_run: If True, only calculate actions without executing
    """
    request_id = self.request.id

    try:
        cache = get_cache()
        secret_manager = get_secret_manager(cache=cache)
        service = QuayReposService(secret_manager=secret_manager)

        result = service.reconcile(orgs=orgs, dry_run=dry_run)

        logger.info(
            f"Task {request_id} completed",
            status=result.status,
            total_actions=len(result.actions),
            applied_count=result.applied_count,
            errors=result.errors,
        )

        return result

    except Exception as err:
        logger.exception(f"Task {request_id} failed with error")
        return QuayReposTaskResult(
            status=TaskStatus.FAILED,
            actions=[],
            applied_count=0,
            errors=[f"Unexpected {err=}"],
        )
