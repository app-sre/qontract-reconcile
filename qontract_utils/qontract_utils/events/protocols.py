from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from qontract_utils.events.models import Event


class EventPublisher(Protocol):
    """Protocol for publishing events to a backend."""

    def publish(self, event: Event) -> str:
        """Publish an event.

        Returns:
            A backend-specific message identifier (e.g., SNS MessageId).
        """
        ...


class EventConsumer(Protocol):
    """Protocol for consuming events from a backend."""

    def receive(
        self, *, block: bool = True, acknowledge: bool = False
    ) -> list[tuple[str, Event]]:
        """Receive pending events.

        Args:
            block: If True, block until events are available.
            acknowledge: If True, automatically acknowledge events after reading.

        Returns:
            List of (receipt_handle, Event) tuples.
        """
        ...

    def acknowledge(self, receipt_handle: str) -> None:
        """Acknowledge successful processing of an event."""
        ...
