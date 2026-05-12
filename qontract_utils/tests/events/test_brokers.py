from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
from qontract_utils.events import RedisBroker

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def mock_fast_broker(mocker: MockerFixture) -> MagicMock:
    mock = mocker.MagicMock()
    mock.connect = AsyncMock()
    mock.stop = AsyncMock()
    mock.publish = AsyncMock(return_value=b"1234567890-0")
    return mock


@pytest.fixture
def broker(mocker: MockerFixture, mock_fast_broker: MagicMock) -> RedisBroker:
    mocker.patch(
        "qontract_utils.events._brokers.FastRedisBroker",
        return_value=mock_fast_broker,
    )
    return RedisBroker(url="redis://localhost:6379")


def test_run_without_context_raises(broker: RedisBroker) -> None:
    coro = AsyncMock()()
    with pytest.raises(RuntimeError, match="Broker is not connected"):
        broker._run(coro)


def test_enter_creates_loop_and_connects(
    broker: RedisBroker, mock_fast_broker: MagicMock
) -> None:
    with broker:
        assert broker._loop is not None
        assert not broker._loop.is_closed()
        mock_fast_broker.connect.assert_awaited_once()


def test_exit_stops_broker_and_closes_loop(
    broker: RedisBroker, mock_fast_broker: MagicMock
) -> None:
    with broker:
        loop = broker._loop

    mock_fast_broker.stop.assert_awaited_once()
    assert loop is not None
    assert loop.is_closed()
    assert broker._loop is None


def test_publish(broker: RedisBroker, mock_fast_broker: MagicMock) -> None:
    with broker:
        result = broker.publish(
            message="test-message",
            stream="test-stream",
            headers={"x-trace": "abc"},
        )

    mock_fast_broker.publish.assert_awaited_once_with(
        "test-message",
        stream="test-stream",
        headers={"x-trace": "abc"},
    )
    assert result == b"1234567890-0"


def test_publish_without_optional_params(
    broker: RedisBroker, mock_fast_broker: MagicMock
) -> None:
    with broker:
        broker.publish(message="msg")

    mock_fast_broker.publish.assert_awaited_once_with(
        "msg",
        stream=None,
        headers=None,
    )


def test_run_with_closed_loop_raises(broker: RedisBroker) -> None:
    with broker:
        pass

    coro = AsyncMock()()
    with pytest.raises(RuntimeError, match="Broker is not connected"):
        broker._run(coro)


def test_exit_closes_loop_even_on_stop_error(
    broker: RedisBroker, mock_fast_broker: MagicMock
) -> None:
    mock_fast_broker.stop = AsyncMock(side_effect=RuntimeError("stop failed"))

    with pytest.raises(RuntimeError, match="stop failed"), broker:
        loop = broker._loop

    assert loop is not None
    assert loop.is_closed()
    assert broker._loop is None


def test_reentry_creates_new_loop(
    broker: RedisBroker, mock_fast_broker: MagicMock
) -> None:
    with broker:
        first_loop = broker._loop

    with broker:
        second_loop = broker._loop

    assert first_loop is not second_loop
    assert mock_fast_broker.connect.await_count == 2
    assert mock_fast_broker.stop.await_count == 2
