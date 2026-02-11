from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qontract_utils.events.factory import create_event_publisher
from qontract_utils.events.models import Event

if TYPE_CHECKING:
    from qontract_utils.events.protocols import EventPublisher

    from qontract_api.cache import CacheBackend
    from qontract_api.config import EventSettings

log = logging.getLogger(__name__)


class EventManager:
    """Manages event publishing for qontract-api.

    Encapsulates the event publisher lifecycle and configuration.
    Publishing failures are logged but never propagated to the caller.
    """

    def __init__(self, publisher: EventPublisher) -> None:
        self._publisher = publisher

    def publish_event(self, event: Event) -> None:
        """Publish a single event. Failures are logged but do not propagate."""
        try:
            self._publisher.publish(event)
        except Exception:
            log.exception(f"Failed to publish event {event.event_type}")

    @classmethod
    def from_config(
        cls, cache: CacheBackend, event_settings: EventSettings
    ) -> EventManager | None:
        """Create an EventManager from configuration.

        Returns None if event publishing is disabled.
        """
        if not event_settings.enabled:
            return None
        publisher = create_event_publisher(
            "redis",
            client=cache.redis_client,
            stream_key=event_settings.stream_key,
        )
        return cls(publisher=publisher)
