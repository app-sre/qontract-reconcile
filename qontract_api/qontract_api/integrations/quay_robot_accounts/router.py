"""FastAPI router for the quay-robot-accounts reconciliation API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotAccountsReconcileRequest,
    QuayRobotAccountsTaskResponse,
    QuayRobotAccountsTaskResult,
)
from qontract_api.integrations.quay_robot_accounts.tasks import (
    reconcile_quay_robot_accounts_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import (
    get_celery_task_result,
    queue_for,
    wait_for_task_completion,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/quay-robot-accounts",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="quay-robot-accounts",
)
def quay_robot_accounts(
    reconcile_request: QuayRobotAccountsReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> QuayRobotAccountsTaskResponse:
    """Queue a quay-robot-accounts reconciliation task."""
    reconcile_quay_robot_accounts_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "organizations": reconcile_request.organizations,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return QuayRobotAccountsTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "quay_robot_accounts_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="quay-robot-accounts-task-status",
)
async def quay_robot_accounts_task_status(
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
) -> QuayRobotAccountsTaskResult:
    """Retrieve the reconciliation result (blocking or non-blocking)."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, QuayRobotAccountsTaskResult
        ),
        timeout_seconds=timeout,
    )
