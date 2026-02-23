from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qontract_utils.events import Event, RedisBroker

if TYPE_CHECKING:
    from qontract_api.config import Settings

log = logging.getLogger(__name__)


class EventManager:
    """Manages event publishing for qontract-api.

    Encapsulates the event publisher lifecycle and configuration.
    Publishing failures are logged but never propagated to the caller.
    """

    def __init__(self, publisher: RedisBroker, channel: str) -> None:
        self._publisher = publisher
        self._channel = channel

    def publish_event(self, event: Event) -> None:
        """Publish a single event. Failures are logged but do not propagate."""
        with self._publisher as publisher:
            try:
                publisher.publish(event, channel=self._channel)
            except Exception:
                log.exception(f"Failed to publish event {event.type}")

    @classmethod
    def from_config(cls, settings: Settings) -> EventManager | None:
        """Create an EventManager from configuration.

        Returns None if event publishing is disabled.
        """
        if not settings.events.enabled:
            return None
        if settings.cache_backend != "redis":
            log.warning(
                "Event publishing is only supported with Redis backend. "
                "EventManager will not be initialized."
            )
            return None
        publisher = RedisBroker(settings.cache_broker_url)
        return cls(publisher=publisher, channel=settings.events.channel)
