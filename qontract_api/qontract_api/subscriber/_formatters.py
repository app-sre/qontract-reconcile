"""Event formatter registry for converting events to human-readable Slack messages."""

import json
from typing import ClassVar, Protocol

from qontract_utils.events._models import Event


class EventFormatter(Protocol):
    """Protocol for event formatters."""

    def format(self, event: Event) -> str:
        """Format an event as a human-readable string.

        Args:
            event: The event to format

        Returns:
            Formatted string representation of the event
        """
        ...


class GenericEventFormatter:
    """Generic event formatter with emoji mapping and JSON data dump."""

    EMOJI_MAP: ClassVar[dict[str, str]] = {
        "error": "🔴",
        "fail": "❌",
        "create": "🟢",
        "update": "🔄",
        "delete": "🗑️",
        "default": "📢",
    }

    def format(self, event: Event) -> str:
        """Format event with emoji, bold event type, source, and JSON data dump.

        Args:
            event: The event to format

        Returns:
            Formatted Slack message with emoji, event type in inline code, source, and JSON data
        """
        emoji = self._get_emoji(event.type)
        json_data = json.dumps(event.data, indent=2, default=str)
        return (
            f"{emoji} Event: `{event.type}`\n"
            f"Source: {event.source}\n"
            f"```\n{json_data}\n```"
        )

    def _get_emoji(self, event_type: str) -> str:
        """Get emoji for event type based on keyword matching.

        Args:
            event_type: The event type string

        Returns:
            Emoji corresponding to the event type, or default emoji
        """
        event_type_lower = event_type.lower()
        for keyword, emoji in self.EMOJI_MAP.items():
            if keyword == "default":
                continue
            if keyword in event_type_lower:
                return emoji
        return self.EMOJI_MAP["default"]


# Module-level registry
_formatters: dict[str, EventFormatter] = {}
_default_formatter = GenericEventFormatter()


def register_formatter(event_type: str, formatter: EventFormatter) -> None:
    """Register a custom formatter for a specific event type.

    Args:
        event_type: The event type to register the formatter for
        formatter: The formatter instance to use for this event type
    """
    _formatters[event_type] = formatter


def format_event(event: Event) -> str:
    """Format an event using the registered formatter or default formatter.

    Args:
        event: The event to format

    Returns:
        Formatted string representation of the event
    """
    formatter = _formatters.get(event.type, _default_formatter)
    return formatter.format(event)
