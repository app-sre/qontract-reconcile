"""FastAPI router for ldap-groups reconciliation."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.integrations.ldap_groups.schemas import (
    LdapGroupsReconcileRequest,
    LdapGroupsTaskResponse,
    LdapGroupsTaskResult,
)
from qontract_api.integrations.ldap_groups.tasks import reconcile_ldap_groups_task
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import (
    get_celery_task_result,
    queue_for,
    wait_for_task_completion,
)

logger = get_logger(__name__)

router = APIRouter(
    prefix="/ldap-groups",
)


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="ldap-groups",
)
def ldap_groups(
    reconcile_request: LdapGroupsReconcileRequest,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    request: Request,
) -> LdapGroupsTaskResponse:
    reconcile_ldap_groups_task.apply_async(
        task_id=request.state.request_id,
        queue=queue_for(dry_run=reconcile_request.dry_run),
        kwargs={
            "connection": reconcile_request.connection,
            "desired_groups": reconcile_request.desired_groups,
            "managed_group_names": reconcile_request.managed_group_names,
            "dry_run": reconcile_request.dry_run,
        },
    )
    return LdapGroupsTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for("ldap_groups_task_status", task_id=request.state.request_id)
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="ldap-groups-task-status",
)
async def ldap_groups_task_status(
    task_id: str,
    current_user: UserDep,  # ruff: ignore[unused-function-argument]
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion.",
        ),
    ] = settings.api_task_default_timeout,
) -> LdapGroupsTaskResult:
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, LdapGroupsTaskResult),
        timeout_seconds=timeout,
    )
