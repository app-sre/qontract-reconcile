"""Event manager for qontract-api."""

from qontract_api.event_manager._base import EventManager
from qontract_api.event_manager._factory import get_event_manager

__all__ = [
    "EventManager",
    "get_event_manager",
]
