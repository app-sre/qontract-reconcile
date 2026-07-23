"""FastAPI router for Slack external API endpoints.

Provides a POST endpoint for sending chat messages or DMs via Slack.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request, status
from qontract_utils.slack_api import SlackApiError

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.slack.schemas import (
    ChatRequest,
    ChatTaskResponse,
    ChatTaskResult,
    ConversationsHistoryParams,
    SlackConversationHistoryResponse,
    SlackMessageAttachmentResponse,
    SlackMessageReactionResponse,
    SlackMessageResponse,
)
from qontract_api.external.slack.tasks import send_slack_chat_message_task
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.slack import create_slack_workspace_client
from qontract_api.tasks import get_celery_task_result, wait_for_task_completion

logger = get_logger(__name__)

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


@router.get(
    "/conversations/history",
    operation_id="slack-conversations-history",
    responses={
        404: {"description": "Channel not found"},
        502: {"description": "Slack API error"},
    },
)
def get_conversations_history(
    _user: UserDep,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
    params: Annotated[
        ConversationsHistoryParams,
        Query(description="Slack conversation history query parameters"),
    ],
) -> SlackConversationHistoryResponse:
    """Get a channel's message history within a timestamp range.

    Args:
        params: workspace_name, channel, from_timestamp/to_timestamp, and secret

    Returns:
        SlackConversationHistoryResponse with messages, newest first

    Raises:
        HTTPException:
            - 404 Not Found: Channel not found
            - 502 Bad Gateway: If Slack API call fails
    """
    client = create_slack_workspace_client(
        secret=params,
        workspace_name=params.workspace_name,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    try:
        messages = client.get_flat_conversation_history(
            channel=params.channel,
            from_timestamp=params.from_timestamp,
            to_timestamp=params.to_timestamp,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except SlackApiError as e:
        logger.exception(
            f"Slack API error fetching conversation history for {params.channel}",
            channel=params.channel,
            workspace=params.workspace_name,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack API error: {e}",
        ) from e

    logger.info(
        f"Fetched {len(messages)} messages from {params.channel}",
        channel=params.channel,
        workspace=params.workspace_name,
        message_count=len(messages),
    )

    return SlackConversationHistoryResponse(
        messages=[
            SlackMessageResponse(
                ts=message.ts,
                text=message.text,
                subtype=message.subtype,
                username=message.username,
                reply_count=message.reply_count,
                reactions=[
                    SlackMessageReactionResponse(name=r.name, count=r.count)
                    for r in message.reactions
                ],
                attachments=[
                    SlackMessageAttachmentResponse(title=a.title, text=a.text)
                    for a in message.attachments
                ],
            )
            for message in messages
        ]
    )
