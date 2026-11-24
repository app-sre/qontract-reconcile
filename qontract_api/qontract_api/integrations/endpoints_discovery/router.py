"""FastAPI router for the endpoints-discovery reconciliation API."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.endpoints_discovery.schemas import (
    EndpointsDiscoveryReconcileRequest,
    EndpointsDiscoveryTaskResponse,
    EndpointsDiscoveryTaskResult,
)
from qontract_api.integrations.endpoints_discovery.tasks import (
    reconcile_endpoints_discovery_task,
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
    prefix="/endpoints-discovery",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="endpoints-discovery",
)
def endpoints_discovery(
    reconcile_request: EndpointsDiscoveryReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> EndpointsDiscoveryTaskResponse:
    """Queue an endpoints-discovery reconciliation task."""
    reconcile_endpoints_discovery_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "request": reconcile_request,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return EndpointsDiscoveryTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "endpoints_discovery_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="endpoints-discovery-task-status",
)
async def endpoints_discovery_task_status(
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
) -> EndpointsDiscoveryTaskResult:
    """Retrieve the reconciliation result (blocking or non-blocking)."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, EndpointsDiscoveryTaskResult
        ),
        timeout_seconds=timeout,
    )
