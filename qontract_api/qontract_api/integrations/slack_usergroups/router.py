"""FastAPI router for Slack usergroups reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResponse,
    SlackUsergroupsTaskResult,
)
from qontract_api.integrations.slack_usergroups.tasks import (
    reconcile_slack_usergroups_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/slack-usergroups",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="slack-usergroups",
)
def slack_usergroups(
    reconcile_request: SlackUsergroupsReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> SlackUsergroupsTaskResponse:
    """Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url
    """
    # Queue Celery task (async execution in background worker)
    reconcile_slack_usergroups_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "workspaces": reconcile_request.workspaces,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return SlackUsergroupsTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        # Note: url_for() uses the function name, not operation_id
        status_url=str(
            request.url_for(
                "slack_usergroups_task_status", task_id=request.state.request_id
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="slack-usergroups-task-status",
)
async def slack_usergroups_task_status(
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
) -> SlackUsergroupsTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, SlackUsergroupsTaskResult
        ),
        timeout_seconds=timeout,
    )
