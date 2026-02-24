"""FastAPI router for Glitchtip project alerts reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.glitchtip_project_alerts.models import (
    GlitchtipProjectAlertsReconcileRequest,
    GlitchtipProjectAlertsTaskResponse,
    GlitchtipProjectAlertsTaskResult,
)
from qontract_api.integrations.glitchtip_project_alerts.tasks import (
    reconcile_glitchtip_project_alerts_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/glitchtip-project-alerts",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="glitchtip-project-alerts",
)
def glitchtip_project_alerts(
    reconcile_request: GlitchtipProjectAlertsReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> GlitchtipProjectAlertsTaskResponse:
    """Queue Glitchtip project alerts reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipProjectAlertsTaskResponse with task_id and status_url
    """
    reconcile_glitchtip_project_alerts_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "instances": reconcile_request.instances,
            "desired_state": reconcile_request.desired_state,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return GlitchtipProjectAlertsTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "glitchtip_project_alerts_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="glitchtip-project-alerts-task-status",
)
async def glitchtip_project_alerts_task_status(
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
) -> GlitchtipProjectAlertsTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipProjectAlertsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, GlitchtipProjectAlertsTaskResult
        ),
        timeout_seconds=timeout,
    )
