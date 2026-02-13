from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.events.models import Event

from reconcile.event_log_sink.integration import (
    EventLogSinkIntegration,
    EventLogSinkParams,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def mock_secret_reader(mocker: MockerFixture) -> MagicMock:
    reader = MagicMock()
    reader.read_all.return_value = {
        "db.endpoint": "localhost",
        "db.port": "6379",
    }
    return reader


@pytest.fixture
def mock_redis(mocker: MockerFixture) -> MagicMock:
    client = MagicMock()
    mocker.patch(
        "reconcile.event_log_sink.integration.Redis"
    ).from_url.return_value = client
    return client


@pytest.fixture
def mock_consumer(mocker: MockerFixture) -> MagicMock:
    consumer = MagicMock()
    mocker.patch(
        "reconcile.event_log_sink.integration.create_event_consumer",
        return_value=consumer,
    )
    return consumer


@pytest.fixture
def sample_event() -> Event:
    return Event(
        event_type="slack-usergroups.update_users",
        source="qontract-api",
        payload={"workspace": "test", "usergroup": "team-a"},
    )


@pytest.fixture
def intg(mock_secret_reader: MagicMock) -> EventLogSinkIntegration:
    integration = EventLogSinkIntegration(
        EventLogSinkParams(
            redis_url_secret_path="secret/redis/url",
        )
    )
    integration._secret_reader = mock_secret_reader  # noqa: SLF001
    return integration
