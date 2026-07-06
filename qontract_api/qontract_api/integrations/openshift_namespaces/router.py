"""FastAPI router for openshift-namespaces reconciliation API.

Implements async-only pattern with blocking GET (ADR-003).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.openshift_namespaces.schemas import (
    OpenShiftNamespacesReconcileRequest,
    OpenShiftNamespacesTaskResponse,
    OpenShiftNamespacesTaskResult,
)
from qontract_api.integrations.openshift_namespaces.tasks import (
    reconcile_openshift_namespaces_task,
)
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

router = APIRouter(prefix="/openshift-namespaces")


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="openshift-namespaces",
)
def openshift_namespaces_reconcile(
    reconcile_request: OpenShiftNamespacesReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> OpenShiftNamespacesTaskResponse:
    """Queue openshift-namespaces reconciliation task."""
    reconcile_openshift_namespaces_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "clusters": reconcile_request.clusters,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return OpenShiftNamespacesTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "openshift_namespaces_reconcile_task_status",
                task_id=request.state.request_id,
            )
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="openshift-namespaces-task-status",
)
async def openshift_namespaces_reconcile_task_status(
    task_id: str,
    current_user: UserDep,  # noqa: ARG001
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion.",
        ),
    ] = settings.api_task_default_timeout,
) -> OpenShiftNamespacesTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking)."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(
            task_id, OpenShiftNamespacesTaskResult
        ),
        timeout_seconds=timeout,
    )
