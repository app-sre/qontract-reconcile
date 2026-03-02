"""FastAPI router for Slack external API endpoints.

Provides a POST endpoint for sending chat messages via Slack.
"""

from fastapi import APIRouter, HTTPException, status
from qontract_utils.slack_api import SlackApiError

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.slack.models import ChatRequest, ChatResponse
from qontract_api.logger import get_logger
from qontract_api.slack import create_slack_workspace_client

logger = get_logger(__name__)

router = APIRouter(
    prefix="/external/slack",
    tags=["external"],
)


@router.post(
    "/chat",
    operation_id="slack-chat-post-message",
)
def post_chat(
    request: ChatRequest,
    _user: UserDep,
    cache: CacheDep,
    secret_manager: SecretManagerDep,
) -> ChatResponse:
    """Post a message to a Slack channel.

    Sends a chat message to the specified channel in the given workspace.
    Supports threaded replies via thread_ts.

    Args:
        request: Chat request with channel, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 502 Bad Gateway: If Slack API call fails
    """
    client = create_slack_workspace_client(
        secret=request.secret,
        workspace_name=request.workspace_name,
        cache=cache,
        secret_manager=secret_manager,
        settings=settings,
    )

    try:
        result = client.chat_post_message(
            channel=request.channel,
            text=request.text,
            thread_ts=request.thread_ts,
            icon_emoji=request.icon_emoji,
            icon_url=request.icon_url,
            username=request.username,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except SlackApiError as e:
        logger.exception(
            f"Slack API error posting to {request.channel}",
            channel=request.channel,
            workspace=request.workspace_name,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack API error: {e}",
        ) from e

    logger.info(
        f"Posted message to {request.channel}",
        channel=request.channel,
        workspace=request.workspace_name,
        ts=result.ts,
    )

    return ChatResponse(
        ts=result.ts,
        channel=result.channel,
        thread_ts=result.thread_ts,
    )
