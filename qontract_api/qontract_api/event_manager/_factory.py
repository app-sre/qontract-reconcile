from qontract_api.config import settings
from qontract_api.event_manager._base import EventManager


def get_event_manager() -> EventManager | None:
    """Create an EventManager from application settings.

    Returns None if event publishing is disabled.
    """
    return EventManager.from_config(settings=settings)
