"""Tests for SlackApi.conversations_open method."""

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from qontract_utils.slack_api import SlackApi


@pytest.fixture
def mock_webclient() -> Generator[MagicMock]:
    """Mock Slack WebClient."""
    with patch("qontract_utils.slack_api.client.WebClient") as mock_client:
        mock_client.return_value.retry_handlers = []
        yield mock_client


@pytest.mark.parametrize(
    ("user_ids", "expected_channel_id"),
    [
        (["U12345"], "D0123ABC"),
        (["U1", "U2"], "G0123ABC"),
    ],
    ids=["single-user-dm", "multi-user-group-dm"],
)
@pytest.mark.usefixtures("mock_webclient")
def test_conversations_open(user_ids: list[str], expected_channel_id: str) -> None:
    """Test conversations_open returns the DM channel ID."""
    api = SlackApi(
        slack_api_url="https://slack.com/api/",
        workspace_name="test-workspace",
        token="xoxb-test-token",
        timeout=30,
        max_retries=5,
    )
    api._sc.conversations_open = MagicMock(  # type: ignore[method-assign]
        return_value={"channel": {"id": expected_channel_id}}
    )

    result = api.conversations_open(user_ids=user_ids)

    assert result == expected_channel_id
    api._sc.conversations_open.assert_called_once_with(users=user_ids)
