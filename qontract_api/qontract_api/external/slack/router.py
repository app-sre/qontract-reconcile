"""FastAPI router for Slack external API endpoints.

Provides a POST endpoint for sending chat messages or DMs via Slack.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from qontract_api.config import settings
from qontract_api.dependencies import UserDep
from qontract_api.external.slack.schemas import (
    ChatRequest,
    ChatTaskResponse,
    ChatTaskResult,
)
from qontract_api.external.slack.tasks import send_slack_chat_message_task
from qontract_api.models import TaskStatus
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

router = APIRouter(
    prefix="/external/slack",
    tags=["external"],
)


@router.post(
    "/chat",
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="slack-chat-post-message",
)
def post_chat(
    request: ChatRequest,
    _user: UserDep,
    http_request: Request,
) -> ChatTaskResponse:
    """Queue a Slack chat message or DM to be sent by a background worker.

    Exactly one of `channel` or `user` must be set in the request:
    - `channel`: post to a Slack channel by name
    - `user`: send a DM to a user by org_username

    This endpoint always queues a background task and returns immediately
    with a task_id. Use GET /chat/{task_id} to retrieve the result.

    Args:
        request: Chat request with channel/user, text, and credentials

    Returns:
        ChatTaskResponse with task_id and status_url
    """
    send_slack_chat_message_task.apply_async(
        task_id=http_request.state.request_id,
        kwargs={"request": request},
    )

    return ChatTaskResponse(
        id=http_request.state.request_id,
        status=TaskStatus.PENDING,
        # Note: url_for() uses the function name, not operation_id
        status_url=str(
            http_request.url_for(
                "get_chat_task_status", task_id=http_request.state.request_id
            )
        ),
    )


@router.get(
    "/chat/{task_id}",
    operation_id="slack-chat-post-message-task-status",
)
async def get_chat_task_status(
    task_id: str,
    _user: UserDep,
    timeout: Annotated[
        int | None,
        Query(
            ge=1,
            le=settings.api_task_max_timeout,
            description="Optional: Block up to N seconds for completion. Omit for immediate status check.",
        ),
    ] = settings.api_task_default_timeout,
) -> ChatTaskResult:
    """Retrieve the chat-post-message result (blocking or non-blocking).

    **Non-blocking mode (default):** Returns immediate status (pending/success/failed)
    **Blocking mode (with timeout):** Waits up to timeout seconds, returns 408 if still pending

    Args:
        task_id: Task ID from POST /chat response
        timeout: Maximum seconds to wait (default: None = non-blocking)

    Returns:
        ChatTaskResult with status and, on success, ts/channel/thread_ts

    Raises:
        HTTPException:
            - 408 Request Timeout: Task still pending after timeout (blocking mode only)
    """
    return await wait_for_task_completion(
        get_task_status=lambda: get_celery_task_result(task_id, ChatTaskResult),
        timeout_seconds=timeout,
    )
