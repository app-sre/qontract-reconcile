from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import ANY, MagicMock

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
    return EventManager(publisher=mock_publisher, stream="test-stream")


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
        mock_publisher.__enter__().publish.assert_called_once_with(  # noqa: PLC2801
            sample_event, stream="test-stream", headers=ANY
        )

    def test_publish_event_failure_does_not_propagate(
        self,
        event_manager: EventManager,
        mock_publisher: MagicMock,
        sample_event: Event,
    ) -> None:
        mock_publisher.__enter__().publish.side_effect = Exception("Redis error")  # noqa: PLC2801
        # Should not raise
        event_manager.publish_event(sample_event)

    def test_from_config_disabled(self, mocker: MockerFixture) -> None:
        mock_settings = mocker.MagicMock()
        mock_settings.events.enabled = False

        result = EventManager.from_config(settings=mock_settings)
        assert result is None

    def test_from_config_enabled(self, mocker: MockerFixture) -> None:
        mock_settings = mocker.MagicMock()
        mock_settings.events.enabled = True
        mock_settings.cache_backend = "redis"
        mock_settings.cache_broker_url = "redis://localhost:6379"

        result = EventManager.from_config(settings=mock_settings)
        assert result is not None
        assert isinstance(result, EventManager)
