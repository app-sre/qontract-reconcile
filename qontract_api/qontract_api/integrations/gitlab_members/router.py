"""FastAPI router for GitLab members reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.gitlab_members.schemas import (
    GitlabMembersReconcileRequest,
    GitlabMembersTaskResponse,
    GitlabMembersTaskResult,
)
from qontract_api.integrations.gitlab_members.tasks import (
    reconcile_gitlab_members_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import (
    get_celery_task_result,
    queue_for,
    wait_for_task_completion,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/gitlab-members")


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="gitlab-members",
)
def gitlab_members(
    reconcile_request: GitlabMembersReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> GitlabMembersTaskResponse:
    """Queue GitLab members reconciliation task.

    Always queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.
    """
    reconcile_gitlab_members_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "instances": reconcile_request.instances,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return GitlabMembersTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "gitlab_members_task_status", task_id=request.state.request_id
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="gitlab-members-task-status",
)
async def gitlab_members_task_status(
    task_id: str,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion. Omit for immediate status check.",
        ),
    ] = settings.api_task_default_timeout,
) -> GitlabMembersTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    Args:
        task_id: Task ID from POST /reconcile response
        timeout: Maximum seconds to wait (default: non-blocking)

    Returns:
        GitlabMembersTaskResult with lists of calculated and applied actions.

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, GitlabMembersTaskResult
        ),
        timeout_seconds=timeout,
    )
