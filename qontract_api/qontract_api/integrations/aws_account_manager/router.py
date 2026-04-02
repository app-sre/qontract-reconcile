"""FastAPI router for AWS account manager API.

Per-account design: each call handles exactly one account.
Implements async-only pattern with blocking GET (see ADR-003).
"""

from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import Response

from qontract_api.cache import cache_workflow, get_cached_task_id
from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, UserDep
from qontract_api.integrations.aws_account_manager.schemas import (
    AWSAccountManagerCreateAccountRequest,
    AWSAccountManagerCreateIAMUserRequest,
    AWSAccountManagerReconcileRequest,
    AWSAccountManagerTaskResponse,
    CreateAccountResult,
    CreateIAMUserResult,
    ReconcileResult,
)
from qontract_api.integrations.aws_account_manager.tasks import (
    create_account_task,
    create_iam_user_task,
    reconcile_account_task,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/aws-account-manager",
)


# --- Create account ---


@router.post(
    "/create-account",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="aws-account-manager-create",
    responses={409: {"model": AWSAccountManagerTaskResponse}},
)
def aws_account_manager_create(
    create_request: AWSAccountManagerCreateAccountRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
    cache: CacheDep,
    response: Response,
) -> AWSAccountManagerTaskResponse:
    """Queue creation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    The task retries itself until the full workflow completes.
    Use GET /create-account/{task_id} to retrieve the result.

    Returns 409 with the original task response if a creation workflow
    for the same request is already in progress.
    """
    if cached_task_id := get_cached_task_id(cache, create_request.workflow_id):
        response.status_code = status.HTTP_409_CONFLICT
        return AWSAccountManagerTaskResponse(
            id=cached_task_id,
            status=TaskStatus.PENDING,
            status_url=str(
                request.url_for(
                    "aws_account_manager_create_status",
                    task_id=cached_task_id,
                ),
            ),
        )

    cache_workflow(
        cache,
        create_request.workflow_id,
        task_id=request.state.request_id,
    )

    create_account_task.apply_async(
        task_id=request.state.request_id,
        kwargs={
            "request": create_request,
            "workflow_id": create_request.workflow_id,
        },
    )

    return AWSAccountManagerTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "aws_account_manager_create_status",
                task_id=request.state.request_id,
            ),
        ),
    )


@router.get(
    "/create-account/{task_id}",
    operation_id="aws-account-manager-create-status",
)
async def aws_account_manager_create_status(
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
) -> CreateAccountResult:
    """Retrieve account creation task result."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, CreateAccountResult),
        timeout_seconds=timeout,
    )


# --- Create IAM user ---


@router.post(
    "/create-iam-user",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="aws-account-manager-create-iam-user",
)
def aws_account_manager_create_iam_user(
    create_request: AWSAccountManagerCreateIAMUserRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> AWSAccountManagerTaskResponse:
    """Queue creation of an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.
    Use GET /create-iam-user/{task_id} to retrieve the result.
    """
    create_iam_user_task.apply_async(
        task_id=request.state.request_id,
        kwargs={"request": create_request},
    )

    return AWSAccountManagerTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "aws_account_manager_create_iam_user_status",
                task_id=request.state.request_id,
            ),
        ),
    )


@router.get(
    "/create-iam-user/{task_id}",
    operation_id="aws-account-manager-create-iam-user-status",
)
async def aws_account_manager_create_iam_user_status(
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
) -> CreateIAMUserResult:
    """Retrieve IAM user creation task result."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, CreateIAMUserResult),
        timeout_seconds=timeout,
    )


# --- Reconcile ---


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="aws-account-manager-reconcile",
)
def aws_account_manager_reconcile(
    reconcile_request: AWSAccountManagerReconcileRequest,
    current_user: UserDep,  # noqa: ARG001
    request: Request,
) -> AWSAccountManagerTaskResponse:
    """Queue reconciliation of a single AWS account.

    Queues a background task and returns immediately with a task_id.
    Use GET /reconcile/{task_id} to retrieve the result.
    """
    reconcile_account_task.apply_async(
        task_id=request.state.request_id,
        kwargs={"request": reconcile_request},
    )

    return AWSAccountManagerTaskResponse(
        id=request.state.request_id,
        status=TaskStatus.PENDING,
        status_url=str(
            request.url_for(
                "aws_account_manager_reconcile_status",
                task_id=request.state.request_id,
            ),
        ),
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="aws-account-manager-reconcile-status",
)
async def aws_account_manager_reconcile_status(
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
) -> ReconcileResult:
    """Retrieve reconciliation task result."""
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, ReconcileResult),
        timeout_seconds=timeout,
    )
