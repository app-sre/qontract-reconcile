"""FastStream subscriber handler for processing events from Redis streams."""

import time

from qontract_utils.events import Event

from qontract_api.logger import get_logger

from ._base import broker
from ._client import post_to_slack
from ._formatters import format_event
from ._metrics import (
    event_processing_duration,
    events_failed,
    events_posted,
    events_received,
)

logger = get_logger(__name__)


@broker.subscriber("main")
async def event_handler(event: Event) -> None:
    """Process events from main stream and post to Slack.

    Per-event error isolation: Exceptions are caught and logged,
    allowing the stream to continue processing subsequent events.

    Args:
        event: CloudEvent from the stream
    """
    events_received.labels(event_type=event.type).inc()
    start_time = time.perf_counter()

    try:
        message = format_event(event)
        await post_to_slack(message)
        events_posted.labels(event_type=event.type).inc()
        logger.info(
            "Event posted to Slack",
            event_type=event.type,
            event_id=str(event.id),
            event_source=event.source,
        )
    except Exception as e:
        logger.exception(
            "Failed to process event",
            event_type=event.type,
            event_id=str(event.id),
            event_source=event.source,
        )
        events_failed.labels(
            event_type=event.type,
            error_type=type(e).__name__,
        ).inc()
        # Don't re-raise — let stream continue (SUB-02)
    finally:
        duration = time.perf_counter() - start_time
        event_processing_duration.labels(event_type=event.type).observe(duration)
