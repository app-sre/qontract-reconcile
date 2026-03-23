"""FastAPI router for the github-owners reconciliation API.

Implements the async-only pattern with blocking GET (see ADR-003).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.github_owners.schemas import (
    GithubOwnersReconcileRequest,
    GithubOwnersTaskResponse,
    GithubOwnersTaskResult,
)
from qontract_api.integrations.github_owners.tasks import (
    reconcile_github_owners_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/github-owners",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="github-owners",
)
def github_owners(
    reconcile_request: GithubOwnersReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> GithubOwnersTaskResponse:
    """Queue a GitHub owners reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired owner state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GithubOwnersTaskResponse with task_id and status_url
    """
    reconcile_github_owners_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "organizations": reconcile_request.organizations,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return GithubOwnersTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "github_owners_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="github-owners-task-status",
)
async def github_owners_task_status(
    task_id: str,
    current_user: UserDep,  # noqa: ARG001
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion. Omit for immediate status check.",
        ),
    ] = settings.api_task_default_timeout,
) -> GithubOwnersTaskResult:
    """Retrieve the reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GithubOwnersTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, GithubOwnersTaskResult),
        timeout_seconds=timeout,
    )
