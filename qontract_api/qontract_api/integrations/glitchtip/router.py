"""FastAPI router for Glitchtip reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.glitchtip.schemas import (
    GlitchtipReconcileRequest,
    GlitchtipTaskResponse,
    GlitchtipTaskResult,
)
from qontract_api.integrations.glitchtip.tasks import reconcile_glitchtip_task
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/glitchtip",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="glitchtip",
)
def glitchtip_reconcile(
    reconcile_request: GlitchtipReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> GlitchtipTaskResponse:
    """Queue Glitchtip reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    Args:
        reconcile_request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        request: FastAPI Request object (used to generate status_url)

    Returns:
        GlitchtipTaskResponse with task_id and status_url
    """
    reconcile_glitchtip_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "instances": reconcile_request.instances,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return GlitchtipTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "glitchtip_reconcile_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="glitchtip-task-status",
)
async def glitchtip_reconcile_task_status(
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
) -> GlitchtipTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status
    **Blocking mode (with timeout):** Waits up to timeout seconds

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        GlitchtipTaskResult with status, actions, applied_count, and errors
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, GlitchtipTaskResult),
        timeout_seconds=timeout,
    )
