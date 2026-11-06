from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest
from qontract_api_client import schemas as qontract_api_schemas
from qontract_api_client.exceptions import HTTPStatusError

from reconcile.slack_base import (
    SlackApi,
    slackapi_from_queries,
    slackapi_from_slack_workspace,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def slack_workspace() -> dict[str, Any]:
    return {
        "workspace": {
            "name": "coreos",
            "integrations": [
                {
                    "name": "dummy",
                    "token": {
                        "path": "some/path",
                        "field": "bot_token",
                    },
                    "channel": "test",
                    "icon_emoji": "test_emoji",
                    "username": "foo",
                },
            ],
        }
    }


@pytest.fixture
def unleash_slack_workspace() -> dict[str, Any]:
    return {
        "workspace": {
            "name": "coreos",
            "integrations": [
                {
                    "name": "slack-usergroups",
                    "token": {
                        "path": "some/path",
                        "field": "bot_token",
                    },
                },
            ],
        },
        "channel": "test",
        "icon_emoji": "unleash",
        "username": "test",
    }


def test_slack_workspace_raises() -> None:
    with pytest.raises(ValueError):
        slackapi_from_slack_workspace({}, "foo")


def test_slack_workspace_ok(slack_workspace: dict[str, Any]) -> None:
    slack_api = slackapi_from_slack_workspace(slack_workspace, "dummy")
    assert slack_api.workspace_name == "coreos"
    assert slack_api.channel == "test"
    assert slack_api.icon_emoji == "test_emoji"
    assert slack_api.username == "foo"
    assert slack_api.token == {"path": "some/path", "field": "bot_token"}


def test_slack_workspace_channel_overwrite(slack_workspace: dict[str, Any]) -> None:
    slack_api = slackapi_from_slack_workspace(slack_workspace, "dummy", channel="foo")
    assert slack_api.channel == "foo"


def test_unleash_workspace_ok(unleash_slack_workspace: dict[str, Any]) -> None:
    slack_api = slackapi_from_slack_workspace(
        unleash_slack_workspace, "slack-usergroups"
    )
    assert slack_api.channel == "test"
    assert slack_api.icon_emoji == "unleash"
    assert slack_api.username == "test"


def test_slackapi_from_queries(
    mocker: MockerFixture, slack_workspace: dict[str, Any]
) -> None:
    mocker.patch(
        "reconcile.slack_base.queries.get_slack_workspace",
        return_value=slack_workspace["workspace"],
    )
    slack_api = slackapi_from_queries("dummy")
    assert slack_api.workspace_name == "coreos"
    assert slack_api.channel == "test"


@pytest.fixture
def mock_config(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "reconcile.slack_base.get_config",
        return_value={"vault": {"server": "https://vault.example.com"}},
    )


@pytest.fixture
def mock_setup_client(mocker: MockerFixture) -> MagicMock:
    return mocker.patch("reconcile.slack_base.setup_qontract_api_client")


def test_chat_post_message_requires_channel(
    mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"})
    with pytest.raises(ValueError):
        slack_api.chat_post_message("hello")


def test_chat_post_message_calls_qontract_api(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    slack_api = SlackApi(
        "coreos",
        token={"path": "some/path", "field": "bot_token", "version": 3},
        channel="test",
        icon_emoji=":robot:",
        username="bot",
    )

    slack_api.chat_post_message("hello world")

    mock_setup_client.assert_called_once()
    mock_send.assert_called_once()
    request = mock_send.call_args.kwargs["data"]
    assert request.workspace_name == "coreos"
    assert request.channel == "test"
    assert request.text == "hello world"
    assert request.icon_emoji == ":robot:"
    assert request.username == "bot"
    assert request.secret.secret_manager_url == "https://vault.example.com"
    assert request.secret.path == "some/path"
    assert request.secret.field == "bot_token"
    assert request.secret.version == 3
    assert request.resolve_mentions is False


def test_chat_post_message_resolve_mentions_opt_in(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    slack_api.chat_post_message("hello @my-cluster-cluster", resolve_mentions=True)

    request = mock_send.call_args.kwargs["data"]
    assert request.resolve_mentions is True


def test_chat_post_message_wait_false_does_not_poll_status(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_status = mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status"
    )
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    slack_api.chat_post_message("hello")

    mock_status.assert_not_called()


def test_chat_post_message_wait_true_succeeds(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_send.return_value.id = "task-123"
    mock_status = mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status"
    )
    mock_status.return_value.status = qontract_api_schemas.TaskStatus.SUCCESS
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    slack_api.chat_post_message("hello", wait=True)

    mock_status.assert_called_once()
    assert mock_status.call_args.kwargs["task_id"] == "task-123"
    # each poll's server-side wait must stay under the sync client's own
    # HTTP timeout, or the client times out before the server can respond
    assert mock_status.call_args.kwargs["timeout"] < 30


def test_chat_post_message_wait_true_raises_on_failure(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_send.return_value.id = "task-123"
    mock_status = mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status"
    )
    mock_status.return_value.status = qontract_api_schemas.TaskStatus.FAILED
    mock_status.return_value.errors = ["Slack API error: channel_not_found"]
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    with pytest.raises(RuntimeError, match="channel_not_found"):
        slack_api.chat_post_message("hello", wait=True)


def test_chat_post_message_wait_true_polls_through_408s(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    """A still-pending task (server 408) is retried, not treated as failure."""
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_send.return_value.id = "task-123"
    pending_response = MagicMock()
    pending_response.status_code = 408
    success_result = MagicMock()
    success_result.status = qontract_api_schemas.TaskStatus.SUCCESS
    mock_status = mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status",
        side_effect=[
            HTTPStatusError(response=pending_response, reason="still pending"),
            HTTPStatusError(response=pending_response, reason="still pending"),
            success_result,
        ],
    )
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    slack_api.chat_post_message("hello", wait=True)

    assert mock_status.call_count == 3


def test_chat_post_message_wait_true_propagates_non_408_errors(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_send.return_value.id = "task-123"
    error_response = MagicMock()
    error_response.status_code = 500
    mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status",
        side_effect=HTTPStatusError(response=error_response, reason="server error"),
    )
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    with pytest.raises(HTTPStatusError):
        slack_api.chat_post_message("hello", wait=True)


def test_chat_post_message_wait_true_raises_after_overall_deadline(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_send = mocker.patch("reconcile.slack_base.slack_chat_post_message")
    mock_send.return_value.id = "task-123"
    pending_response = MagicMock()
    pending_response.status_code = 408
    mocker.patch(
        "reconcile.slack_base.slack_chat_post_message_task_status",
        side_effect=HTTPStatusError(response=pending_response, reason="still pending"),
    )
    # one poll happens within the deadline (still pending), then the clock
    # advances past the overall wait deadline before the next check
    times = iter([0, 50, 301])
    mocker.patch("reconcile.slack_base.time.monotonic", side_effect=lambda: next(times))
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"}, channel="test")

    with pytest.raises(RuntimeError, match="did not complete within"):
        slack_api.chat_post_message("hello", wait=True)
