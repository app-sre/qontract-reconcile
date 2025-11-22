"""FastAPI router for Slack usergroups reconciliation API.

Implements async-only pattern with blocking GET (see ADR-003).
"""

import os
import time
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, UserDep
from qontract_api.integrations.slack_usergroups.models import (
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResponse,
    SlackUsergroupsTaskResult,
)
from qontract_api.integrations.slack_usergroups.service import SlackUsergroupsService
from qontract_api.integrations.slack_usergroups.slack_factory import (
    create_slack_workspace_client,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.tasks.utils import wait_for_task_completion

logger = get_logger(__name__)

router = APIRouter(
    prefix="/slack-usergroups",
)


def get_slack_token_from_vault(vault_path: str) -> str:
    """Retrieve Slack token from vault path.

    TEMPORARY IMPLEMENTATION: Reads from environment variable.
    Production implementation should use VaultClient to fetch secret.

    This function is injected into the service to keep it decoupled from
    Vault implementation details (Dependency Injection pattern).

    Args:
        vault_path: Vault path to the Slack token
                   (e.g., "app-sre/integrations-output/slack-workspace-1/slack-api-token")

    Returns:
        Slack API token

    Raises:
        HTTPException: If token cannot be retrieved

    TODO: Replace with actual Vault call. Production implementation should use
    VaultClient to fetch secret from vault_path.
    """
    # Placeholder: Read from env var
    env_var = (
        f"TMP_SLACK_TOKEN_{vault_path.replace('/', '_').replace('-', '_').upper()}"
    )
    token = os.getenv(env_var)
    if not token:
        msg = (
            f"Slack token not found for vault path {vault_path}. "
            f"Set environment variable {env_var} (TODO: Vault integration)"
        )
        logger.error(msg, extra={"vault_path": vault_path, "env_var": env_var})
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=msg,
        )
    return token


@router.post(
    "/reconcile",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="slack-usergroups",
)
def slack_usergroups(
    request: SlackUsergroupsReconcileRequest,
    current_user: UserDep,
    cache: CacheDep,
) -> SlackUsergroupsTaskResponse:
    """Queue Slack usergroups reconciliation task.

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /reconcile/{task_id} to retrieve the result.

    See ADR-003 for rationale: docs/adr/ADR-003-async-only-api-with-blocking-get.md

    Args:
        request: Reconciliation request with desired state
        current_user: Authenticated user (from JWT token)
        cache: Cache backend for Slack API responses

    Returns:
        SlackUsergroupsTaskResponse with task_id and status_url

    Raises:
        HTTPException: If cache not available or Slack token not found
    """
    logger.info(
        f"Queuing reconciliation task for user {current_user.username}",
        extra={
            "username": current_user.username,
            "dry_run": request.dry_run,
            "workspace_count": len(request.workspaces),
        },
    )

    # TODO: Implement task queue in Teilaufgabe 3
    # For now, store request in cache with PENDING status
    # This is a TEMPORARY placeholder until task queue is implemented
    task_id = f"temp-{int(time.time() * 1000)}"
    status_url = f"/api/v1/integrations/slack-usergroups/reconcile/{task_id}"

    logger.warning(
        "Task queue not yet implemented, using placeholder task_id",
        extra={"username": current_user.username, "task_id": task_id},
    )

    # Store request in cache temporarily (will be replaced by task queue)
    # Using cache as temporary storage until task queue backend is implemented
    cache.set_obj(f"task:{task_id}:request", request, ttl=600)
    cache.set(f"task:{task_id}:status", TaskStatus.PENDING, ttl=600)

    logger.info(
        f"Task queued: {task_id}",
        extra={
            "username": current_user.username,
            "task_id": task_id,
            "status_url": status_url,
        },
    )

    return SlackUsergroupsTaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        status_url=status_url,
    )


@router.get(
    "/reconcile/{task_id}",
    operation_id="slack-usergroups-task-status",
)
async def slack_usergroups_task_status(
    task_id: str,
    current_user: UserDep,
    cache: CacheDep,
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion. Omit for immediate status check.",
        ),
    ] = settings.api_task_default_timeout,
) -> SlackUsergroupsTaskResult:
    """Retrieve reconciliation result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    See ADR-003 for rationale: docs/adr/ADR-003-async-only-api-with-blocking-get.md

    Args:
        task_id: Task ID from POST /reconcile response
        current_user: Authenticated user (from JWT token)
        cache: Cache backend for task status/results
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        SlackUsergroupsTaskResult with status, actions, applied_count, and errors

    Raises:
        HTTPException:
            - 404 Not Found: Task ID not found
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    logger.info(
        f"Retrieving result for task {task_id}",
        extra={
            "username": current_user.username,
            "task_id": task_id,
            "timeout": timeout,
            "blocking": timeout is not None,
        },
    )

    def get_task_status() -> SlackUsergroupsTaskResult:
        """Get current task status - executed on-demand or polled.

        This function is called by wait_for_task_completion helper.
        Integration-specific logic for status retrieval.
        """
        # Check if task exists
        task_status = cache.get(f"task:{task_id}:status")
        if task_status is None:
            logger.error(
                f"Task not found: {task_id}",
                extra={"username": current_user.username, "task_id": task_id},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} not found",
            )

        # If task already completed, return cached result
        if task_status != TaskStatus.PENDING:
            result = cache.get_obj(f"task:{task_id}:result", SlackUsergroupsTaskResult)
            if result:
                logger.info(
                    f"Returning cached result for task {task_id}",
                    extra={
                        "username": current_user.username,
                        "task_id": task_id,
                        "status": result.status,
                    },
                )
                return result

        # Task still pending - execute it (TEMPORARY until task queue implemented)
        logger.info(
            f"Task {task_id} still pending, executing now",
            extra={"username": current_user.username, "task_id": task_id},
        )

        request = cache.get_obj(
            f"task:{task_id}:request", SlackUsergroupsReconcileRequest
        )
        if request is None:
            logger.error(
                f"Task request data not found: {task_id}",
                extra={"username": current_user.username, "task_id": task_id},
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Task {task_id} request data not found",
            )

        # Execute reconciliation
        service = SlackUsergroupsService(
            cache=cache,
            settings=settings,
            get_slack_token=get_slack_token_from_vault,
            create_slack_client=create_slack_workspace_client,
        )
        result = service.reconcile(
            workspaces=request.workspaces,
            dry_run=request.dry_run,
        )

        # Cache result
        cache.set_obj(f"task:{task_id}:result", result, ttl=600)
        cache.set(f"task:{task_id}:status", result.status, ttl=600)
        cache.delete(f"task:{task_id}:request")  # Clean up

        logger.info(
            f"Task {task_id} completed with status {result.status}",
            extra={
                "username": current_user.username,
                "task_id": task_id,
                "status": result.status,
                "total_actions": len(result.actions),
                "applied_count": result.applied_count,
            },
        )

        return result

    # Use generic helper (handles blocking vs non-blocking)
    return await wait_for_task_completion(
        get_task_status=get_task_status,
        timeout_seconds=timeout,
    )
