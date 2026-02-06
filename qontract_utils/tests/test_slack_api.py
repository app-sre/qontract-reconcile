"""Tests for qontract_utils.slack_api module."""

# ruff: noqa: ARG001

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.slack_api import SlackApi, SlackChannel, SlackUser, SlackUsergroup

# Default values for tests (matching typical settings)
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 5
DEFAULT_SLACK_API_URL = "https://slack.com/api/"


@pytest.fixture
def mock_webclient() -> Generator[MagicMock, None, None]:
    """Mock Slack WebClient."""
    with patch("qontract_utils.slack_api.client.WebClient") as mock_client:
        mock_client.return_value.retry_handlers = []
        yield mock_client


@pytest.fixture
def slack_api(mock_webclient: MagicMock) -> SlackApi:
    """Create SlackApi instance with mocked WebClient."""
    return SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="test-workspace",
        token="xoxb-test-token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )


def test_slack_api_method_configs(mock_webclient: MagicMock) -> None:
    """Test SlackApi with method-specific configurations."""
    method_configs: dict[str, dict[str, Any]] = {
        "users.list": {"limit": 1000},
        "conversations.list": {"limit": 500},
    }
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        method_configs=method_configs,
    )

    assert api._method_configs["users.list"] == {"limit": 1000}
    assert api._method_configs["conversations.list"] == {"limit": 500}


def test_slack_api_webclient_created_with_timeout(mock_webclient: MagicMock) -> None:
    """Test WebClient is created with correct timeout."""
    SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=15,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    mock_webclient.assert_called_once()
    call_kwargs = mock_webclient.call_args.kwargs
    assert call_kwargs["timeout"] == 15


def test_slack_api_retry_handlers_configured(mock_webclient: MagicMock) -> None:
    """Test retry handlers are added to WebClient."""
    SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=7,
    )

    mock_webclient.assert_called_once()
    call_kwargs = mock_webclient.call_args.kwargs
    assert "retry_handlers" in call_kwargs
    assert len(call_kwargs["retry_handlers"]) == 3


def test_slack_api_workspace_name(mock_webclient: MagicMock) -> None:
    """Test workspace_name is stored correctly."""
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="test-workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    assert api.workspace_name == "test-workspace"


def test_slack_api_pre_hooks_includes_metrics(mock_webclient: MagicMock) -> None:
    """Test that metrics hook is always included."""
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    # Should have at least the metrics hook
    assert len(api._pre_hooks) >= 1


def test_slack_api_pre_hooks_custom(mock_webclient: MagicMock) -> None:
    """Test custom hooks are added after metrics hook."""
    custom_hook = MagicMock()
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        pre_hooks=[custom_hook],
    )

    # Should have metrics + latency_start + request_log + custom hook
    assert len(api._pre_hooks) == 4
    assert api._pre_hooks[-1] == custom_hook


def test_slack_api_post_hooks_includes_latency(mock_webclient: MagicMock) -> None:
    """Test that latency hook is always included in post_hooks."""
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
    )

    # Should have at least the latency_end hook
    assert len(api._post_hooks) >= 1


def test_slack_api_post_hooks_custom(mock_webclient: MagicMock) -> None:
    """Test custom post_hooks are added after latency hook."""
    custom_hook = MagicMock()
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        post_hooks=[custom_hook],
    )

    # Should have latency_end hook + custom hook
    assert len(api._post_hooks) == 2
    assert api._post_hooks[-1] == custom_hook


def test_slack_api_error_hooks_custom(mock_webclient: MagicMock) -> None:
    """Test custom error_hooks are added."""
    custom_hook = MagicMock()
    api = SlackApi(
        slack_api_url=DEFAULT_SLACK_API_URL,
        workspace_name="workspace",
        token="token",
        timeout=DEFAULT_TIMEOUT,
        max_retries=DEFAULT_MAX_RETRIES,
        error_hooks=[custom_hook],
    )

    # Should have custom error hook
    assert len(api._error_hooks) == 1
    assert api._error_hooks[0] == custom_hook


# Typed methods tests


def test_users_list_returns_slack_user_objects(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test users_list returns list of SlackUser objects."""
    mock_response = {
        "members": [
            {
                "id": "U1",
                "name": "alice",
                "deleted": False,
                "profile": {"email": "alice@example.com"},
            },
            {
                "id": "U2",
                "name": "bob",
                "deleted": False,
                "profile": {"email": "bob@example.com"},
            },
        ],
        "response_metadata": {"next_cursor": ""},
    }
    slack_api._sc.api_call = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    users = slack_api.users_list()

    assert len(users) == 2
    assert all(isinstance(user, SlackUser) for user in users)
    assert users[0].id == "U1"
    assert users[0].name == "alice"
    assert users[1].id == "U2"


def test_users_list_handles_pagination(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test users_list handles pagination with cursor."""
    mock_response_page1 = {
        "members": [{"id": "U1", "name": "alice", "deleted": False, "profile": {}}],
        "response_metadata": {"next_cursor": "cursor123"},
    }
    mock_response_page2 = {
        "members": [{"id": "U2", "name": "bob", "deleted": False, "profile": {}}],
        "response_metadata": {"next_cursor": ""},
    }

    slack_api._sc.api_call = MagicMock(  # type: ignore[method-assign]
        side_effect=[mock_response_page1, mock_response_page2]
    )

    users = slack_api.users_list()

    assert len(users) == 2
    assert slack_api._sc.api_call.call_count == 2


def test_usergroups_list_returns_slack_usergroup_objects(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_list returns list of SlackUsergroup objects."""
    mock_response: dict[str, Any] = {
        "usergroups": [
            {
                "id": "UG1",
                "handle": "oncall",
                "name": "On-Call",
                "description": "On-call team",
                "users": ["U1", "U2"],
                "prefs": {"channels": ["C1"]},
            }
        ]
    }
    slack_api._sc.usergroups_list = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroups = slack_api.usergroups_list()

    assert len(usergroups) == 1
    assert isinstance(usergroups[0], SlackUsergroup)
    assert usergroups[0].id == "UG1"
    assert usergroups[0].handle == "oncall"
    assert len(usergroups[0].users) == 2
    assert usergroups[0].prefs.channels == ["C1"]


def test_usergroups_list_with_include_users_false(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_list passes include_users parameter and always includes disabled."""
    mock_response: dict[str, Any] = {"usergroups": []}
    slack_api._sc.usergroups_list = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    slack_api.usergroups_list(include_users=False)

    slack_api._sc.usergroups_list.assert_called_once_with(
        include_users=False, include_disabled=True
    )


def test_usergroups_create_returns_slack_usergroup(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_create returns SlackUsergroup object."""
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "newteam",
            "name": "newteam",
            "description": "",
            "users": [],
            "prefs": {"channels": []},
        }
    }
    slack_api._sc.usergroups_create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroup = slack_api.usergroup_create(handle="newteam")

    assert isinstance(usergroup, SlackUsergroup)
    assert usergroup.id == "UG1"
    assert usergroup.handle == "newteam"
    slack_api._sc.usergroups_create.assert_called_once_with(
        name="newteam", handle="newteam"
    )


def test_usergroups_create_with_custom_name(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_create uses custom name if provided."""
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "team",
            "name": "Custom Team Name",
            "description": "",
            "users": [],
            "prefs": {"channels": []},
        }
    }
    slack_api._sc.usergroups_create = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    slack_api.usergroup_create(handle="team", name="Custom Team Name")

    slack_api._sc.usergroups_create.assert_called_once_with(
        name="Custom Team Name", handle="team"
    )


def test_usergroups_update_returns_slack_usergroup(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_update returns updated SlackUsergroup object."""
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "oncall",
            "name": "Updated Name",
            "description": "Updated description",
            "users": [],
            "prefs": {"channels": []},
        }
    }
    slack_api._sc.usergroups_update = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroup = slack_api.usergroup_update(
        usergroup_id="UG1",
        name="Updated Name",
        description="Updated description",
    )

    assert isinstance(usergroup, SlackUsergroup)
    assert usergroup.name == "Updated Name"
    assert usergroup.description == "Updated description"


def test_usergroup_enable_returns_slack_usergroup(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroup_enable returns enabled SlackUsergroup object."""
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "oncall",
            "name": "On-Call",
            "description": "",
            "users": [],
            "prefs": {"channels": []},
            "date_delete": 0,  # 0 means not disabled
        }
    }
    slack_api._sc.usergroups_enable = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroup = slack_api.usergroup_enable(usergroup_id="UG1")

    assert isinstance(usergroup, SlackUsergroup)
    assert usergroup.id == "UG1"
    slack_api._sc.usergroups_enable.assert_called_once_with(usergroup="UG1")


def test_usergroup_disable_returns_slack_usergroup(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroup_disable returns disabled SlackUsergroup object."""
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "oncall",
            "name": "On-Call",
            "description": "",
            "users": [],
            "prefs": {"channels": []},
            "date_delete": 1234567890,  # non-zero means disabled
        }
    }
    slack_api._sc.usergroups_disable = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroup = slack_api.usergroup_disable(usergroup_id="UG1")

    assert isinstance(usergroup, SlackUsergroup)
    assert usergroup.id == "UG1"
    slack_api._sc.usergroups_disable.assert_called_once_with(usergroup="UG1")


def test_usergroups_users_update_returns_slack_usergroup(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test usergroups_users_update returns updated SlackUsergroup object.

    SlackApi only accepts IDs (user_ids parameter).
    """
    mock_response = {
        "usergroup": {
            "id": "UG1",
            "handle": "oncall",
            "name": "",
            "description": "",
            "users": ["U1", "U2", "U3"],
            "prefs": {"channels": []},
        }
    }
    slack_api._sc.usergroups_users_update = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    usergroup = slack_api.usergroup_users_update(
        usergroup_id="UG1",
        user_ids=["U1", "U2", "U3"],
    )

    assert isinstance(usergroup, SlackUsergroup)
    assert len(usergroup.users) == 3
    # Verify SlackApi calls Slack WebClient with correct parameters
    slack_api._sc.usergroups_users_update.assert_called_once_with(
        usergroup="UG1", users=["U1", "U2", "U3"]
    )


def test_conversations_list_returns_slack_channel_objects(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test conversations_list returns list of SlackChannel objects."""
    mock_response = {
        "channels": [
            {"id": "C1", "name": "general", "is_archived": False, "is_member": True},
            {"id": "C2", "name": "random", "is_archived": False, "is_member": False},
        ],
        "response_metadata": {"next_cursor": ""},
    }
    slack_api._sc.api_call = MagicMock(return_value=mock_response)  # type: ignore[method-assign]

    channels = slack_api.conversations_list()

    assert len(channels) == 2
    assert all(isinstance(channel, SlackChannel) for channel in channels)
    assert channels[0].id == "C1"
    assert channels[0].name == "general"
    assert channels[0].is_member is True


def test_conversations_list_handles_pagination(
    slack_api: SlackApi, mock_webclient: MagicMock
) -> None:
    """Test conversations_list handles pagination."""
    mock_response_page1 = {
        "channels": [
            {"id": "C1", "name": "general", "is_archived": False, "is_member": False}
        ],
        "response_metadata": {"next_cursor": "cursor456"},
    }
    mock_response_page2 = {
        "channels": [
            {"id": "C2", "name": "random", "is_archived": False, "is_member": False}
        ],
        "response_metadata": {"next_cursor": ""},
    }

    slack_api._sc.api_call = MagicMock(  # type: ignore[method-assign]
        side_effect=[mock_response_page1, mock_response_page2]
    )

    channels = slack_api.conversations_list()

    assert len(channels) == 2
    assert slack_api._sc.api_call.call_count == 2


def test_slack_api_retries_on_transient_errors(
    mock_webclient: MagicMock, enable_retry: None
) -> None:
    """Test that SlackApi retries on transient errors."""
    from slack_sdk.errors import SlackApiError

    api = SlackApi(
        slack_api_url="https://slack.com/api/",
        workspace_name="test",
        token="xoxb-test",
        timeout=30,
        max_retries=0,
    )

    # Mock: first 2 calls fail, 3rd succeeds
    call_count = {"count": 0}

    def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]  # noqa: ANN002, ANN003, ANN202
        call_count["count"] += 1
        if call_count["count"] < 3:
            raise SlackApiError("rate_limited", response=MagicMock())
        return {
            "usergroups": [
                {
                    "id": "UG1",
                    "handle": "oncall",
                    "name": "On-Call",
                    "description": "",
                    "users": [],
                    "prefs": {"channels": []},
                }
            ]
        }

    api._sc.usergroups_list = MagicMock(side_effect=side_effect)  # type: ignore[method-assign]

    result = api.usergroups_list()

    assert len(result) == 1
    assert call_count["count"] == 3


def test_slack_api_gives_up_after_max_attempts(
    mock_webclient: MagicMock, enable_retry: None
) -> None:
    """Test that SlackApi gives up after max retry attempts."""
    from slack_sdk.errors import SlackApiError

    api = SlackApi(
        slack_api_url="https://slack.com/api/",
        workspace_name="test",
        token="xoxb-test",
        timeout=30,
        max_retries=0,
    )

    # Mock: always fails
    call_count = {"count": 0}

    def side_effect(*args, **kwargs):  # type: ignore[no-untyped-def]  # noqa: ANN002, ANN003, ANN202
        call_count["count"] += 1
        raise SlackApiError("always fails", response=MagicMock())

    api._sc.usergroups_list = MagicMock(side_effect=side_effect)  # type: ignore[method-assign]

    with pytest.raises(SlackApiError):
        api.usergroups_list()

    # Should have tried 3 times (attempts=3)
    assert call_count["count"] == 3
