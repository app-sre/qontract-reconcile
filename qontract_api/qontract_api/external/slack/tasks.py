"""Celery task for sending a Slack chat message or DM.

Runs in a Celery worker rather than the FastAPI request-handling thread, so a
slow or rate-limited Slack response doesn't block the API server (see PR
review discussion on app-sre/qontract-reconcile#5692).
"""

from __future__ import annotations

from typing import Any

from qontract_utils.slack_api import SlackApiError, UserNotFoundError

from qontract_api.cache.factory import get_cache
from qontract_api.config import settings
from qontract_api.external.slack.schemas import ChatRequest, ChatTaskResult
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus
from qontract_api.secret_manager._factory import get_secret_manager
from qontract_api.slack import create_slack_workspace_client
from qontract_api.tasks import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, name="external-slack.chat-post-message", acks_late=True)
def send_slack_chat_message_task(self: Any, request: ChatRequest) -> ChatTaskResult:
    """Post a Slack message or DM (background task).

    This task runs in a Celery worker, not in the FastAPI application.
    Uses global cache instance (get_cache()) shared across all tasks in worker.

    Args:
        self: Celery task instance (bind=True)
        request: Chat request with channel/user, text, and credentials

    Returns:
        ChatTaskResult with status and, on success, ts/channel/thread_ts
    """
    request_id = self.request.id
    cache = get_cache()
    secret_manager = get_secret_manager(cache=cache)

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
        target = request.user or request.channel
        logger.warning(
            f"Task {request_id}: target not found: {e}",
            target=target,
            workspace=request.workspace_name,
        )
        return ChatTaskResult(status=TaskStatus.FAILED, errors=[str(e)])
    except SlackApiError as e:
        target = request.user or request.channel
        logger.exception(
            f"Task {request_id}: Slack API error posting to {target}",
            target=target,
            workspace=request.workspace_name,
        )
        return ChatTaskResult(
            status=TaskStatus.FAILED, errors=[f"Slack API error: {e}"]
        )

    target = request.user or request.channel
    logger.info(
        f"Task {request_id}: posted message to {target}",
        target=target,
        workspace=request.workspace_name,
        ts=result.ts,
    )

    return ChatTaskResult(
        status=TaskStatus.SUCCESS,
        applied_count=1,
        ts=result.ts,
        channel=result.channel,
        thread_ts=result.thread_ts,
    )
