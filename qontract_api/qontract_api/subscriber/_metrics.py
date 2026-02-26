"""Prometheus metrics for event subscriber."""

from prometheus_client import Counter, Histogram

from ._base import registry

# Counter for total events received from the stream
events_received = Counter(
    "qontract_reconcile_subscriber_events_received_total",
    "Total events received from stream",
    labelnames=["event_type"],
    registry=registry,
)

# Counter for total events successfully posted to Slack
events_posted = Counter(
    "qontract_reconcile_subscriber_events_posted_total",
    "Total events posted to Slack",
    labelnames=["event_type"],
    registry=registry,
)

# Counter for total events that failed processing
events_failed = Counter(
    "qontract_reconcile_subscriber_events_failed_total",
    "Total events that failed processing",
    labelnames=["event_type", "error_type"],
    registry=registry,
)

# Histogram for event processing latency
event_processing_duration = Histogram(
    "qontract_reconcile_subscriber_event_processing_duration_seconds",
    "Event processing latency",
    labelnames=["event_type"],
    registry=registry,
)
