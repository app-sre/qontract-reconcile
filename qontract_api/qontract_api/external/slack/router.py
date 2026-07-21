"""FastAPI router for Slack external API endpoints.

Provides a POST endpoint for sending chat messages or DMs via Slack.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from qontract_utils.slack_api import SlackApiError, UserNotFoundError

from qontract_api.config import settings
from qontract_api.dependencies import CacheDep, SecretManagerDep, UserDep
from qontract_api.external.slack.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationsHistoryParams,
    SlackConversationHistoryResponse,
    SlackMessageAttachmentResponse,
    SlackMessageReactionResponse,
    SlackMessageResponse,
)
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
    """Post a message to a Slack channel or send a DM to a user.

    Exactly one of `channel` or `user` must be set in the request:
    - `channel`: post to a Slack channel by name
    - `user`: send a DM to a user by org_username

    Args:
        request: Chat request with channel/user, text, and credentials

    Returns:
        ChatResponse with ts, channel, and optional thread_ts

    Raises:
        HTTPException:
            - 404 Not Found: Channel or user not found
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
        if request.user:
            result = client.send_dm(
                org_username=request.user,
                text=request.text,
            )
        else:
            assert request.channel  # guaranteed by model_validator
            result = client.chat_post_message(
                channel=request.channel,
                text=request.text,
                thread_ts=request.thread_ts,
                icon_emoji=request.icon_emoji,
                icon_url=request.icon_url,
                username=request.username,
            )
    except (ValueError, UserNotFoundError) as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except SlackApiError as e:
        target = request.user or request.channel
        logger.exception(
            f"Slack API error posting to {target}",
            target=target,
            workspace=request.workspace_name,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Slack API error: {e}",
        ) from e

    target = request.user or request.channel
    logger.info(
        f"Posted message to {target}",
        target=target,
        workspace=request.workspace_name,
        ts=result.ts,
    )

    return ChatResponse(
        ts=result.ts,
        channel=result.channel,
        thread_ts=result.thread_ts,
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
