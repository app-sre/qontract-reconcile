"""Tests for _publish_dm_notifications in slack usergroups tasks."""

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from qontract_api.integrations.slack_usergroups.schemas import (
    SlackUsergroupActionUpdateUsers,
)
from qontract_api.integrations.slack_usergroups.tasks import (
    _DM_NOTIFICATION_EVENT_TYPE,
    _publish_dm_notifications,
)
from qontract_api.slack.domain import NotificationAddUser, NotificationRemoveUser

if TYPE_CHECKING:
    from qontract_utils.events import Event


@pytest.fixture
def mock_event_manager() -> MagicMock:
    return MagicMock()


def test_publish_dm_add_notification(mock_event_manager: MagicMock) -> None:
    """Test DM event published for users_to_add when NotificationAddUser is configured."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice", "bob"],
        users_to_add=["alice"],
        users_to_remove=["charlie"],
        notifications=[NotificationAddUser(message="Welcome to @oncall!")],
    )

    _publish_dm_notifications(mock_event_manager, action)

    mock_event_manager.publish_event.assert_called_once()
    event: Event = mock_event_manager.publish_event.call_args[0][0]
    assert event.type == _DM_NOTIFICATION_EVENT_TYPE
    assert event.data == {
        "usergroup": "oncall",
        "users": ["alice"],
        "message": "Welcome to @oncall!",
    }


def test_publish_dm_remove_notification(mock_event_manager: MagicMock) -> None:
    """Test DM event published for users_to_remove when NotificationRemoveUser is configured."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice"],
        users_to_add=["alice"],
        users_to_remove=["charlie"],
        notifications=[NotificationRemoveUser(message="You have been removed.")],
    )

    _publish_dm_notifications(mock_event_manager, action)

    mock_event_manager.publish_event.assert_called_once()
    event: Event = mock_event_manager.publish_event.call_args[0][0]
    assert event.data["users"] == ["charlie"]
    assert event.data["message"] == "You have been removed."


def test_publish_dm_both_notifications(mock_event_manager: MagicMock) -> None:
    """Test two separate events published when both add and remove notifications configured."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice"],
        users_to_add=["alice"],
        users_to_remove=["charlie"],
        notifications=[
            NotificationAddUser(message="Welcome!"),
            NotificationRemoveUser(message="Goodbye!"),
        ],
    )

    _publish_dm_notifications(mock_event_manager, action)

    assert mock_event_manager.publish_event.call_count == 2
    events = [c[0][0] for c in mock_event_manager.publish_event.call_args_list]
    assert events[0].data["users"] == ["alice"]
    assert events[0].data["message"] == "Welcome!"
    assert events[1].data["users"] == ["charlie"]
    assert events[1].data["message"] == "Goodbye!"


def test_publish_dm_skips_add_when_no_users_to_add(
    mock_event_manager: MagicMock,
) -> None:
    """Test no event published for NotificationAddUser when users_to_add is empty."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice"],
        users_to_add=[],
        users_to_remove=["charlie"],
        notifications=[NotificationAddUser(message="Welcome!")],
    )

    _publish_dm_notifications(mock_event_manager, action)

    mock_event_manager.publish_event.assert_not_called()


def test_publish_dm_skips_remove_when_no_users_to_remove(
    mock_event_manager: MagicMock,
) -> None:
    """Test no event published for NotificationRemoveUser when users_to_remove is empty."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice"],
        users_to_add=["alice"],
        users_to_remove=[],
        notifications=[NotificationRemoveUser(message="Goodbye!")],
    )

    _publish_dm_notifications(mock_event_manager, action)

    mock_event_manager.publish_event.assert_not_called()


def test_publish_dm_no_notifications_configured(
    mock_event_manager: MagicMock,
) -> None:
    """Test no events published when notifications list is empty."""
    action = SlackUsergroupActionUpdateUsers(
        workspace="coreos",
        usergroup="oncall",
        users=["alice"],
        users_to_add=["alice"],
        users_to_remove=[],
        notifications=[],
    )

    _publish_dm_notifications(mock_event_manager, action)

    mock_event_manager.publish_event.assert_not_called()
