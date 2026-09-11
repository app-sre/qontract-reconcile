"""FastAPI router for managed-sso-client reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.managed_sso_client.schemas import (
    ManagedSsoClientReconcileRequest,
    ManagedSsoClientTaskResponse,
    ManagedSsoClientTaskResult,
)
from qontract_api.integrations.managed_sso_client.tasks import (
    reconcile_managed_sso_client_task,
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
    prefix="/managed-sso-client",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="managed-sso-client",
)
def managed_sso_client(
    reconcile_request: ManagedSsoClientReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> ManagedSsoClientTaskResponse:
    """Queue a managed-sso-client reconciliation task."""
    reconcile_managed_sso_client_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "desired_clients": reconcile_request.desired_clients,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return ManagedSsoClientTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "managed_sso_client_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="managed-sso-client-task-status",
)
async def managed_sso_client_task_status(
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
) -> ManagedSsoClientTaskResult:
    """Retrieve the reconciliation result (blocking or non-blocking)."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, ManagedSsoClientTaskResult
        ),
        timeout_seconds=timeout,
    )
