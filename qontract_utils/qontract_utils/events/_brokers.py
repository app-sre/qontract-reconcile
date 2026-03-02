import asyncio
from collections.abc import Coroutine
from typing import Any, Self

from faststream.redis import RedisBroker as FastRedisBroker
from faststream.types import SendableMessage


class RedisBroker:
    """Synchronous wrapper around faststream's RedisBroker for publishing messages."""

    def __init__(self, url: str) -> None:
        self._broker = FastRedisBroker(url)
        self._loop: asyncio.AbstractEventLoop | None = None

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        if self._loop is None or self._loop.is_closed():
            raise RuntimeError("Broker is not connected. Use as context manager.")
        return self._loop.run_until_complete(coro)

    def __enter__(self) -> Self:
        self._loop = asyncio.new_event_loop()
        self._run(self._broker.connect())
        return self

    def __exit__(self, *args: object) -> None:
        try:
            self._run(self._broker.stop())
        finally:
            if self._loop and not self._loop.is_closed():
                self._loop.close()
            self._loop = None

    def publish(
        self,
        message: SendableMessage,
        stream: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> int | bytes:
        """Publish a message to a Redis Stream."""
        return self._run(self._broker.publish(message, stream=stream, headers=headers))
