"""Tests for SlackWorkspaceClient.send_dm and _resolve_user_id."""
from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.slack_api import (
    ChatPostMessageResponse,
    SlackUser,
    SlackUserProfile,
    UserNotFoundError,
)

from qontract_api.slack.slack_workspace_client import (
    CachedUsers,
    SlackWorkspaceClient,
)

if TYPE_CHECKING:
    from qontract_api.config import Settings


@pytest.fixture
def client(
    mock_slack_api: MagicMock, mock_cache: MagicMock, mock_settings: Settings
) -> SlackWorkspaceClient:
    """Create SlackWorkspaceClient with mocks."""
    return SlackWorkspaceClient(
        slack_api=mock_slack_api,
        cache=mock_cache,
        settings=mock_settings,
    )


@pytest.fixture
def cached_users() -> CachedUsers:
    """Create cached users fixture."""
    return CachedUsers(
        items=[
            SlackUser(
                id="U1",
                name="Alice",
                deleted=False,
                profile=SlackUserProfile(email="alice@example.com"),
            ),
            SlackUser(
                id="U2",
                name="Bob",
                deleted=False,
                profile=SlackUserProfile(email="bob@example.com"),
            ),
        ]
    )


@pytest.mark.parametrize(
    ("org_username", "expected_id"),
    [("alice", "U1"), ("bob", "U2")],
)
def test_resolve_user_id_found(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
    cached_users: CachedUsers,
    org_username: str,
    expected_id: str,
) -> None:
    """Test _resolve_user_id returns user ID for known org_username."""
    mock_cache.get_obj.return_value = cached_users

    assert client._resolve_user_id(org_username) == expected_id


def test_resolve_user_id_not_found(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
    cached_users: CachedUsers,
) -> None:
    """Test _resolve_user_id raises UserNotFoundError for unknown org_username."""
    mock_cache.get_obj.return_value = cached_users

    with pytest.raises(UserNotFoundError, match="unknown"):
        client._resolve_user_id("unknown")


def test_send_dm_success(
    client: SlackWorkspaceClient,
    mock_slack_api: MagicMock,
    mock_cache: MagicMock,
    cached_users: CachedUsers,
) -> None:
    """Test send_dm resolves user, opens DM channel, sends message."""
    mock_cache.get_obj.return_value = cached_users
    mock_slack_api.conversations_open.return_value = "D_DM_CHANNEL"
    mock_slack_api.chat_post_message.return_value = ChatPostMessageResponse(
        ts="1234567890.000000",
        channel="D_DM_CHANNEL",
    )

    result = client.send_dm(org_username="alice", text="Hello!")

    mock_slack_api.conversations_open.assert_called_once_with(user_ids=["U1"])
    mock_slack_api.chat_post_message.assert_called_once_with(
        channel_id="D_DM_CHANNEL",
        text="Hello!",
    )
    assert result.ts == "1234567890.000000"
    assert result.channel == "D_DM_CHANNEL"


def test_send_dm_user_not_found(
    client: SlackWorkspaceClient,
    mock_cache: MagicMock,
    cached_users: CachedUsers,
) -> None:
    """Test send_dm raises UserNotFoundError for unknown user."""
    mock_cache.get_obj.return_value = cached_users

    with pytest.raises(UserNotFoundError, match="nonexistent"):
        client.send_dm(org_username="nonexistent", text="Hello!")
