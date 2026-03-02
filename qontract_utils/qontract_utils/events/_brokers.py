import asyncio
from collections.abc import Coroutine
from typing import Any, Self

from faststream.redis import RedisBroker as FastRedisBroker
from faststream.types import SendableMessage


class RedisBroker:
    """Synchronous wrapper around faststream's RedisBroker for publishing messages."""

    def __init__(self, url: str) -> None:
        self._broker = FastRedisBroker(url)
        self._loop = asyncio.new_event_loop()

    def _run(self, coro: Coroutine[Any, Any, Any]) -> Any:
        return self._loop.run_until_complete(coro)

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def connect(self) -> None:
        """Establish the Redis connection."""
        self._run(self._broker.connect())

    def close(self) -> None:
        """Close the connection and event loop."""
        self._run(self._broker.stop())
        self._loop.close()

    def publish(
        self,
        message: SendableMessage,
        stream: str | None = None,
        headers: dict[str, Any] | None = None,
    ) -> int | bytes:
        """Publish a message to a Redis Stream."""
        return self._run(self._broker.publish(message, stream=stream, headers=headers))
