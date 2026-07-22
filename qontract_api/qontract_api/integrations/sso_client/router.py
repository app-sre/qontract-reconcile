"""FastAPI router for RHIDP SSO client reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.sso_client.schemas import (
    SsoClientReconcileRequest,
    SsoClientTaskResponse,
    SsoClientTaskResult,
)
from qontract_api.integrations.sso_client.tasks import reconcile_sso_client_task
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import (
    get_celery_task_result,
    queue_for,
    wait_for_task_completion,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/sso-client",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="sso-client",
)
def sso_client(
    reconcile_request: SsoClientReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> SsoClientTaskResponse:
    """Queue RHIDP SSO client reconciliation task.

    This endpoint always queues a background task and returns immediately with a
    task_id. Use GET /reconcile/{task_id} to retrieve the result.
    """
    reconcile_sso_client_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "ocm_environment": reconcile_request.ocm_environment,
            "clusters": reconcile_request.clusters,
            "keycloak_secrets": reconcile_request.keycloak_secrets,
            "vault_target": reconcile_request.vault_target,
            "dry_run": reconcile_request.dry_run,
        },
    )

    return SsoClientTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for("sso_client_task_status", task_id=request.state.request_id)
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="sso-client-task-status",
)
async def sso_client_task_status(
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
) -> SsoClientTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking)."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, SsoClientTaskResult),
        timeout_seconds=timeout,
    )
