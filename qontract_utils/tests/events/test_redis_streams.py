from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, call

import pytest
from qontract_utils.events.models import Event
from qontract_utils.events.redis_streams import (
    RedisStreamsEventConsumer,
    RedisStreamsEventPublisher,
)

if TYPE_CHECKING:
    from pytest_mock import MockerFixture

STREAM_KEY = "qontract:events"
CONSUMER_GROUP = "test-group"
CONSUMER_NAME = "test-consumer"


@pytest.fixture
def mock_redis(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock()


@pytest.fixture
def consumer(mock_redis: MagicMock) -> RedisStreamsEventConsumer:
    return RedisStreamsEventConsumer(
        client=mock_redis,
        stream_key=STREAM_KEY,
        consumer_group=CONSUMER_GROUP,
        consumer_name=CONSUMER_NAME,
    )


class TestRedisStreamsEventPublisher:
    def test_publish(self, mock_redis: MagicMock) -> None:
        mock_redis.xadd.return_value = "1234567890-0"
        publisher = RedisStreamsEventPublisher(client=mock_redis, stream_key=STREAM_KEY)

        event = Event(
            event_type="slack-usergroups.update_users",
            source="qontract-api",
            payload={"workspace": "test"},
        )
        result = publisher.publish(event)

        assert result == "1234567890-0"
        mock_redis.xadd.assert_called_once_with(
            STREAM_KEY,
            {"event": event.model_dump_json()},
        )


class TestRedisStreamsEventConsumer:
    def test_ensure_consumer_group_created(self, mock_redis: MagicMock) -> None:
        RedisStreamsEventConsumer(
            client=mock_redis,
            stream_key=STREAM_KEY,
            consumer_group=CONSUMER_GROUP,
            consumer_name=CONSUMER_NAME,
        )
        mock_redis.xgroup_create.assert_called_once_with(
            STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True
        )

    def test_ensure_consumer_group_already_exists(
        self, mock_redis: MagicMock
    ) -> None:
        mock_redis.xgroup_create.side_effect = Exception("BUSYGROUP")
        # Should not raise
        RedisStreamsEventConsumer(
            client=mock_redis,
            stream_key=STREAM_KEY,
            consumer_group=CONSUMER_GROUP,
            consumer_name=CONSUMER_NAME,
        )

    def test_receive_returns_pending_first(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        event = Event(
            event_type="pending.event",
            source="test",
            payload={},
        )
        # First call (pending with ID "0") returns a pending event
        mock_redis.xreadgroup.return_value = [
            (STREAM_KEY, [("111-0", {"event": event.model_dump_json()})])
        ]

        result = consumer.receive()

        assert len(result) == 1
        assert result[0][0] == "111-0"
        assert result[0][1].event_type == "pending.event"
        # Only the pending call (ID "0") should have been made
        mock_redis.xreadgroup.assert_called_once_with(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={STREAM_KEY: "0"},
            count=10,
        )

    def test_receive_reads_new_when_no_pending(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        event = Event(
            event_type="new.event",
            source="test",
            payload={},
        )
        # First call (pending with ID "0") returns empty
        # Second call (new with ID ">") returns an event
        mock_redis.xreadgroup.side_effect = [
            None,
            [(STREAM_KEY, [("222-0", {"event": event.model_dump_json()})])],
        ]

        result = consumer.receive()

        assert len(result) == 1
        assert result[0][1].event_type == "new.event"
        assert mock_redis.xreadgroup.call_count == 2
        mock_redis.xreadgroup.assert_has_calls([
            call(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: "0"},
                count=10,
            ),
            call(
                groupname=CONSUMER_GROUP,
                consumername=CONSUMER_NAME,
                streams={STREAM_KEY: ">"},
                count=10,
                block=30000,
            ),
        ])

    def test_receive_non_blocking(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        mock_redis.xreadgroup.return_value = None

        consumer.receive(block=False)

        # Second call (new messages) should use block=None
        assert mock_redis.xreadgroup.call_args_list[1] == call(
            groupname=CONSUMER_GROUP,
            consumername=CONSUMER_NAME,
            streams={STREAM_KEY: ">"},
            count=10,
            block=None,
        )

    def test_receive_empty(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        mock_redis.xreadgroup.return_value = None

        result = consumer.receive()
        assert result == []

    def test_acknowledge(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        consumer.acknowledge("1234567890-0")

        mock_redis.xack.assert_called_once_with(
            STREAM_KEY, CONSUMER_GROUP, "1234567890-0"
        )

    def test_receive_auto_acknowledge(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        event = Event(event_type="test.event", source="test", payload={})
        # Pending returns empty, new returns an event
        mock_redis.xreadgroup.side_effect = [
            None,
            [(STREAM_KEY, [("333-0", {"event": event.model_dump_json()})])],
        ]

        result = consumer.receive(acknowledge=True)

        assert len(result) == 1
        mock_redis.xack.assert_called_once_with(STREAM_KEY, CONSUMER_GROUP, "333-0")

    def test_receive_no_auto_acknowledge_by_default(
        self, mock_redis: MagicMock, consumer: RedisStreamsEventConsumer
    ) -> None:
        event = Event(event_type="test.event", source="test", payload={})
        mock_redis.xreadgroup.side_effect = [
            None,
            [(STREAM_KEY, [("444-0", {"event": event.model_dump_json()})])],
        ]

        consumer.receive()

        mock_redis.xack.assert_not_called()
