from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from qontract_api_client import schemas as qontract_api_schemas

from reconcile.slack_base import (
    SlackApi,
    slackapi_from_queries,
    slackapi_from_slack_workspace,
)

if TYPE_CHECKING:
    from unittest.mock import MagicMock

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


def test_get_flat_conversation_history_requires_channel(
    mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    slack_api = SlackApi("coreos", token={"path": "p", "field": "f"})
    with pytest.raises(ValueError):
        slack_api.get_flat_conversation_history(from_timestamp=1, to_timestamp=None)


def test_get_flat_conversation_history_calls_qontract_api(
    mocker: MockerFixture, mock_config: MagicMock, mock_setup_client: MagicMock
) -> None:
    mock_messages = [qontract_api_schemas.SlackMessageResponse(ts="1.0", text="hi")]
    mock_fetch = mocker.patch(
        "reconcile.slack_base.slack_conversations_history",
        return_value=qontract_api_schemas.SlackConversationHistoryResponse(
            messages=mock_messages
        ),
    )
    slack_api = SlackApi(
        "coreos", token={"path": "some/path", "field": "bot_token"}, channel="test"
    )

    result = slack_api.get_flat_conversation_history(
        from_timestamp=100, to_timestamp=200
    )

    assert result == mock_messages
    mock_fetch.assert_called_once_with(
        secret_manager_url="https://vault.example.com",
        path="some/path",
        field="bot_token",
        version=None,
        workspace_name="coreos",
        channel="test",
        from_timestamp=100,
        to_timestamp=200,
    )
