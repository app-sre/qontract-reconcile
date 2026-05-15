"""Tests for SlackApi.conversations_open method."""

# ruff: noqa: ARG001

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.slack_api import SlackApi


@pytest.fixture
def mock_webclient() -> Generator[MagicMock, None, None]:
    """Mock Slack WebClient."""
    with patch("qontract_utils.slack_api.client.WebClient") as mock_client:
        mock_client.return_value.retry_handlers = []
        yield mock_client


def test_conversations_open_returns_channel_id(mock_webclient: MagicMock) -> None:
    """Test conversations_open returns the DM channel ID."""
    api = SlackApi(
        slack_api_url="https://slack.com/api/",
        workspace_name="test-workspace",
        token="xoxb-test-token",
        timeout=30,
        max_retries=5,
    )
    api._sc.conversations_open = MagicMock(  # type: ignore[method-assign]
        return_value={"channel": {"id": "D0123ABC"}}
    )

    result = api.conversations_open(user_ids=["U12345"])

    assert result == "D0123ABC"
    api._sc.conversations_open.assert_called_once_with(users=["U12345"])


def test_conversations_open_multiple_users(mock_webclient: MagicMock) -> None:
    """Test conversations_open with multiple user IDs (group DM)."""
    api = SlackApi(
        slack_api_url="https://slack.com/api/",
        workspace_name="test-workspace",
        token="xoxb-test-token",
        timeout=30,
        max_retries=5,
    )
    api._sc.conversations_open = MagicMock(  # type: ignore[method-assign]
        return_value={"channel": {"id": "G0123ABC"}}
    )

    result = api.conversations_open(user_ids=["U1", "U2"])

    assert result == "G0123ABC"
    api._sc.conversations_open.assert_called_once_with(users=["U1", "U2"])
