"""FastAPI router for Quay repos reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.quay_repos.schemas import (
    QuayReposReconcileRequest,
    QuayReposTaskResponse,
    QuayReposTaskResult,
)
from qontract_api.integrations.quay_repos.tasks import reconcile_quay_repos_task
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import (
    get_celery_task_result,
    queue_for,
    wait_for_task_completion,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/quay-repos")


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="quay-repos",
)
def quay_repos(
    reconcile_request: QuayReposReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> QuayReposTaskResponse:
    """Queue Quay repos reconciliation task.

    Always queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.
    """
    reconcile_quay_repos_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "orgs": reconcile_request.orgs,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return QuayReposTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for("quay_repos_task_status", task_id=request.state.request_id)
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="quay-repos-task-status",
)
async def quay_repos_task_status(
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
) -> QuayReposTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    Args:
        task_id: Task ID from POST /reconcile response
        timeout: Maximum seconds to wait (default: non-blocking)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, QuayReposTaskResult),
        timeout_seconds=timeout,
    )
