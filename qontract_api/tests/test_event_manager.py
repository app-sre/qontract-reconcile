from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.events import Event

from qontract_api.event_manager import EventManager

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def mock_publisher(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock()


@pytest.fixture
def event_manager(mock_publisher: MagicMock) -> EventManager:
    return EventManager(publisher=mock_publisher)


@pytest.fixture
def sample_event() -> Event:
    return Event(
        source="qontract-api",
        type="slack-usergroups.update_users",
        data={"workspace": "test"},
    )


class TestEventManager:
    def test_publish_event(
        self,
        event_manager: EventManager,
        mock_publisher: MagicMock,
        sample_event: Event,
    ) -> None:
        event_manager.publish_event(sample_event)
        mock_publisher.publish.assert_called_once_with(sample_event)

    def test_publish_event_failure_does_not_propagate(
        self,
        event_manager: EventManager,
        mock_publisher: MagicMock,
        sample_event: Event,
    ) -> None:
        mock_publisher.publish.side_effect = Exception("Redis error")
        # Should not raise
        event_manager.publish_event(sample_event)

    def test_from_config_disabled(self, mocker: MockerFixture) -> None:
        mock_settings = mocker.MagicMock()
        mock_settings.enabled = False

        result = EventManager.from_config(settings=mock_settings)
        assert result is None

    def test_from_config_enabled(self, mocker: MockerFixture) -> None:
        mock_settings = mocker.MagicMock()
        mock_settings.enabled = True

        mocker.patch(
            "qontract_api.event_manager._base.create_event_publisher",
        )

        result = EventManager.from_config(settings=mock_settings)
        assert result is not None
        assert isinstance(result, EventManager)
