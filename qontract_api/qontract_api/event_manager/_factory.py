from qontract_api.cache import CacheBackend
from qontract_api.config import settings
from qontract_api.event_manager._base import EventManager


def get_event_manager(cache: CacheBackend) -> EventManager | None:
    """Create an EventManager from application settings.

    Returns None if event publishing is disabled.
    """
    return EventManager.from_config(cache=cache, event_settings=settings.events)
