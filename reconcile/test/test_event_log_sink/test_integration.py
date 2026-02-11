from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from qontract_utils.events.models import Event

if TYPE_CHECKING:
    from unittest.mock import MagicMock

    from pytest_mock import MockerFixture

    from reconcile.event_log_sink.integration import EventLogSinkIntegration


def test_run_reads_redis_url_from_vault(
    intg: EventLogSinkIntegration,
    mock_secret_reader: MagicMock,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
) -> None:
    mock_consumer.receive.side_effect = KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=False)

    mock_secret_reader.read_all.assert_called_once_with(
        {"path": "secret/redis/url"},
    )


def test_run_uses_same_consumer_group_for_dry_run(
    intg: EventLogSinkIntegration,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
    mocker: MockerFixture,
) -> None:
    mock_create = mocker.patch(
        "reconcile.event_log_sink.integration.create_event_consumer",
        return_value=mock_consumer,
    )
    mock_consumer.receive.side_effect = KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=True)

    mock_create.assert_called_once_with(
        "redis",
        client=mock_redis,
        stream_key="qontract:events",
        consumer_group="event-log-sink",
        consumer_name="default",
    )


def test_run_receive_with_acknowledge(
    intg: EventLogSinkIntegration,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
    sample_event: Event,
) -> None:
    mock_consumer.receive.side_effect = [
        [("msg-1", sample_event)],
        KeyboardInterrupt,
    ]

    with pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=False)

    mock_consumer.receive.assert_called_with(block=True, acknowledge=True)


def test_run_dry_run_receive_without_acknowledge(
    intg: EventLogSinkIntegration,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
    sample_event: Event,
) -> None:
    mock_consumer.receive.side_effect = [
        [("msg-1", sample_event)],
        KeyboardInterrupt,
    ]

    with pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=True)

    mock_consumer.receive.assert_called_with(block=True, acknowledge=False)


def test_run_logs_events(
    intg: EventLogSinkIntegration,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
    sample_event: Event,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mock_consumer.receive.side_effect = [
        [("msg-1", sample_event)],
        KeyboardInterrupt,
    ]

    with caplog.at_level(logging.INFO), pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=False)

    assert "type=slack-usergroups.update_users" in caplog.text
    assert "source=qontract-api" in caplog.text
    mock_redis.close.assert_called_once()


def test_run_multiple_events(
    intg: EventLogSinkIntegration,
    mock_redis: MagicMock,
    mock_consumer: MagicMock,
) -> None:
    event1 = Event(event_type="test.one", source="src", payload={"a": 1})
    event2 = Event(event_type="test.two", source="src", payload={"b": 2})
    mock_consumer.receive.side_effect = [
        [("msg-1", event1), ("msg-2", event2)],
        KeyboardInterrupt,
    ]

    with pytest.raises(KeyboardInterrupt):
        intg.run(dry_run=False)

    mock_redis.close.assert_called_once()
