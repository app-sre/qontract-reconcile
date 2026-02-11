from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from qontract_utils.events.models import Event

if TYPE_CHECKING:
    from redis import Redis

log = logging.getLogger(__name__)


class RedisStreamsEventPublisher:
    """Publishes events to a Redis Stream."""

    def __init__(self, client: Redis, stream_key: str) -> None:
        self.client = client
        self.stream_key = stream_key

    def publish(self, event: Event) -> str:
        """Publish an event to a Redis Stream via XADD."""
        message_id = str(
            self.client.xadd(
                self.stream_key,
                {"event": event.model_dump_json()},
            )
        )
        log.info(
            f"Published event {event.event_type} to {self.stream_key}, message_id={message_id}"
        )
        return message_id


class RedisStreamsEventConsumer:
    """Consumes events from a Redis Stream using consumer groups.

    Standard message queue behavior:
    - receive() returns pending (unacknowledged) events first, then new ones
    - Call acknowledge() after successful processing to remove from PEL
    - Without acknowledge(), the same events are returned on the next receive()
    """

    def __init__(
        self,
        client: Redis,
        stream_key: str,
        consumer_group: str,
        consumer_name: str,
    ) -> None:
        self.client = client
        self.stream_key = stream_key
        self.consumer_group = consumer_group
        self.consumer_name = consumer_name
        self._ensure_consumer_group()

    def _ensure_consumer_group(self) -> None:
        """Create the consumer group if it does not exist."""
        with contextlib.suppress(Exception):
            self.client.xgroup_create(
                self.stream_key,
                self.consumer_group,
                id="0",
                mkstream=True,
            )

    @staticmethod
    def _parse_response(response: object) -> list[tuple[str, Event]]:
        events: list[tuple[str, Event]] = []
        for _stream_key, messages in response or []:  # type: ignore[attr-defined]
            for message_id, data in messages:
                event = Event.model_validate_json(data["event"])
                events.append((message_id, event))
        return events

    def receive(
        self, *, block: bool = True, acknowledge: bool = False
    ) -> list[tuple[str, Event]]:
        """Receive events from the Redis Stream.

        Returns pending (unacknowledged) events first. If none are pending,
        reads new events from the stream. Without acknowledge, the same
        events will be returned on the next call.

        Args:
            block: If True, block for up to 30 seconds waiting for new events.
            acknowledge: If True, automatically acknowledge events after reading.
        """
        # First: return pending (unacknowledged) events from PEL
        pending = self.client.xreadgroup(
            groupname=self.consumer_group,
            consumername=self.consumer_name,
            streams={self.stream_key: "0"},
            count=10,
        )

        if events := self._parse_response(pending):
            if acknowledge:
                for message_id, _ in events:
                    self.acknowledge(message_id)
            return events

        # No pending events: read new ones
        response = self.client.xreadgroup(
            groupname=self.consumer_group,
            consumername=self.consumer_name,
            streams={self.stream_key: ">"},
            count=10,
            block=30000 if block else None,
        )
        events = self._parse_response(response)
        if acknowledge:
            for message_id, _ in events:
                self.acknowledge(message_id)
        return events

    def acknowledge(self, message_id: str) -> None:
        """Acknowledge a processed message via XACK."""
        self.client.xack(self.stream_key, self.consumer_group, message_id)
