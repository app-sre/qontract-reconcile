from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from qontract_utils.events.factory import create_event_consumer, create_event_publisher
from qontract_utils.events.redis_streams import (
    RedisStreamsEventConsumer,
    RedisStreamsEventPublisher,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


STREAM_KEY = "qontract:events"


@pytest.fixture
def mock_aws_api(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock()


@pytest.fixture
def mock_redis(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock()


class TestCreateEventPublisher:
    def test_redis_backend(self, mock_redis: MagicMock) -> None:
        publisher = create_event_publisher(
            "redis", client=mock_redis, stream_key=STREAM_KEY
        )
        assert isinstance(publisher, RedisStreamsEventPublisher)

    def test_unknown_backend(self, mock_redis: MagicMock) -> None:
        with pytest.raises(ValueError, match="Unknown event publisher backend"):
            create_event_publisher("kafka", client=mock_redis, stream_key=STREAM_KEY)


class TestCreateEventConsumer:
    def test_redis_backend(self, mock_redis: MagicMock) -> None:
        consumer = create_event_consumer(
            "redis",
            client=mock_redis,
            stream_key=STREAM_KEY,
            consumer_group="test-group",
            consumer_name="test-consumer",
        )
        assert isinstance(consumer, RedisStreamsEventConsumer)

    def test_unknown_backend(self, mock_redis: MagicMock) -> None:
        with pytest.raises(ValueError, match="Unknown event consumer backend"):
            create_event_consumer("kafka", client=mock_redis, stream_key=STREAM_KEY)
