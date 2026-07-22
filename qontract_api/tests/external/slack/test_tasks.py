"""Unit tests for the Slack chat-post-message Celery task."""

from unittest.mock import MagicMock, patch

from qontract_utils.slack_api import (
    ChatPostMessageResponse,
    SlackApiError,
    UserNotFoundError,
)

from qontract_api.external.slack.schemas import ChatRequest, ChatTaskResult
from qontract_api.external.slack.tasks import send_slack_chat_message_task
from qontract_api.models import Secret, TaskStatus


def _chat_request(**overrides: object) -> ChatRequest:
    defaults: dict[str, object] = {
        "workspace_name": "test-workspace",
        "channel": "sd-app-sre-reconcile",
        "text": "Hello from qontract-api",
        "secret": Secret(
            secret_manager_url="https://vault.example.com",
            path="app-sre/slack/bot-token",
        ),
    }
    defaults.update(overrides)
    return ChatRequest(**defaults)


def _run_task(request: ChatRequest) -> ChatTaskResult:
    """Execute the Celery task eagerly (in-process, no broker) and return its result."""
    return send_slack_chat_message_task.apply(kwargs={"request": request}).get()


@patch("qontract_api.external.slack.tasks.get_cache")
@patch("qontract_api.external.slack.tasks.get_secret_manager")
@patch("qontract_api.external.slack.tasks.create_slack_workspace_client")
def test_task_posts_to_channel_success(
    mock_factory: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Task posts to a channel and returns a successful result."""
    mock_client = MagicMock()
    mock_client.chat_post_message.return_value = ChatPostMessageResponse(
        ts="1234567890.123456", channel="C12345"
    )
    mock_factory.return_value = mock_client

    result = _run_task(_chat_request())

    assert isinstance(result, ChatTaskResult)
    assert result.status == TaskStatus.SUCCESS
    assert result.applied_count == 1
    assert result.ts == "1234567890.123456"
    assert result.channel == "C12345"
    mock_client.chat_post_message.assert_called_once_with(
        channel="sd-app-sre-reconcile",
        text="Hello from qontract-api",
        thread_ts=None,
        icon_emoji=None,
        icon_url=None,
        username=None,
    )


@patch("qontract_api.external.slack.tasks.get_cache")
@patch("qontract_api.external.slack.tasks.get_secret_manager")
@patch("qontract_api.external.slack.tasks.create_slack_workspace_client")
def test_task_sends_dm_success(
    mock_factory: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Task sends a DM when `user` is set instead of `channel`."""
    mock_client = MagicMock()
    mock_client.send_dm.return_value = ChatPostMessageResponse(
        ts="1234567890.123456", channel="D12345"
    )
    mock_factory.return_value = mock_client

    result = _run_task(_chat_request(channel=None, user="jsmith"))

    assert result.status == TaskStatus.SUCCESS
    mock_client.send_dm.assert_called_once_with(
        org_username="jsmith", text="Hello from qontract-api"
    )


@patch("qontract_api.external.slack.tasks.get_cache")
@patch("qontract_api.external.slack.tasks.get_secret_manager")
@patch("qontract_api.external.slack.tasks.create_slack_workspace_client")
def test_task_target_not_found_returns_failed(
    mock_factory: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Task returns a FAILED result (not an exception) when the target isn't found."""
    mock_client = MagicMock()
    mock_client.chat_post_message.side_effect = ValueError("Channel 'x' not found")
    mock_factory.return_value = mock_client

    result = _run_task(_chat_request())

    assert result.status == TaskStatus.FAILED
    assert "not found" in result.errors[0]


@patch("qontract_api.external.slack.tasks.get_cache")
@patch("qontract_api.external.slack.tasks.get_secret_manager")
@patch("qontract_api.external.slack.tasks.create_slack_workspace_client")
def test_task_user_not_found_returns_failed(
    mock_factory: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Task returns a FAILED result when the DM target user isn't found."""
    mock_client = MagicMock()
    mock_client.send_dm.side_effect = UserNotFoundError("User 'x' not found")
    mock_factory.return_value = mock_client

    result = _run_task(_chat_request(channel=None, user="nobody"))

    assert result.status == TaskStatus.FAILED
    assert "not found" in result.errors[0]


@patch("qontract_api.external.slack.tasks.get_cache")
@patch("qontract_api.external.slack.tasks.get_secret_manager")
@patch("qontract_api.external.slack.tasks.create_slack_workspace_client")
def test_task_slack_api_error_returns_failed(
    mock_factory: MagicMock,
    mock_get_secret_manager: MagicMock,
    mock_get_cache: MagicMock,
) -> None:
    """Task returns a FAILED result (not an exception) on a Slack API error."""
    mock_client = MagicMock()
    error_response = MagicMock()
    error_response.__getitem__ = MagicMock(return_value="channel_not_found")
    mock_client.chat_post_message.side_effect = SlackApiError(
        "channel_not_found", response=error_response
    )
    mock_factory.return_value = mock_client

    result = _run_task(_chat_request())

    assert result.status == TaskStatus.FAILED
    assert "Slack API error" in result.errors[0]
