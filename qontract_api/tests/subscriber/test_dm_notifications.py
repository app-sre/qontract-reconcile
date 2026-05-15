"""Tests for DM notification handling in subscriber."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from qontract_utils.events import Event

from qontract_api.subscriber._subscriptions import (
    _handle_dm_notifications,
    event_handler,
)


@pytest.fixture
def dm_notification_event() -> Event:
    """Create a DM notification event."""
    return Event(
        source="test-source",
        type="qontract-api.slack-usergroups.dm-notification",
        data={
            "usergroup": "oncall-team",
            "users": ["alice@example.com", "bob@example.com"],
            "message": "You have been added to @oncall-team.",
        },
    )


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.send_dm", new_callable=AsyncMock)
async def test_handle_dm_notifications_sends_dm_per_user(
    mock_send_dm: AsyncMock,
    dm_notification_event: Event,
) -> None:
    """Test _handle_dm_notifications sends a DM to each user."""
    await _handle_dm_notifications(dm_notification_event)

    assert mock_send_dm.call_count == 2
    mock_send_dm.assert_any_call(
        org_username="alice@example.com",
        text="You have been added to @oncall-team.",
    )
    mock_send_dm.assert_any_call(
        org_username="bob@example.com",
        text="You have been added to @oncall-team.",
    )


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.send_dm", new_callable=AsyncMock)
async def test_handle_dm_notifications_isolates_per_user_errors(
    mock_send_dm: AsyncMock,
    dm_notification_event: Event,
) -> None:
    """Test one failed DM does not block others."""
    mock_send_dm.side_effect = [Exception("DM failed"), None]

    await _handle_dm_notifications(dm_notification_event)

    assert mock_send_dm.call_count == 2


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.send_dm", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event")
async def test_event_handler_dispatches_dm_notification(
    mock_format: MagicMock,
    mock_post: AsyncMock,
    mock_send_dm: AsyncMock,
    dm_notification_event: Event,
) -> None:
    """Test event_handler dispatches dm-notification events to _handle_dm_notifications."""
    await event_handler(dm_notification_event)

    assert mock_send_dm.call_count == 2
    mock_format.assert_not_called()
    mock_post.assert_not_called()


@pytest.mark.asyncio
@patch("qontract_api.subscriber._subscriptions.send_dm", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.post_to_slack", new_callable=AsyncMock)
@patch("qontract_api.subscriber._subscriptions.format_event", return_value="formatted")
async def test_event_handler_non_dm_events_use_default_path(
    mock_format: MagicMock,
    mock_post: AsyncMock,
    mock_send_dm: AsyncMock,
    sample_event: Event,
) -> None:
    """Test non-DM events still go through format_event + post_to_slack."""
    await event_handler(sample_event)

    mock_format.assert_called_once_with(sample_event)
    mock_post.assert_called_once_with("formatted")
    mock_send_dm.assert_not_called()
