"""Prometheus metrics for event subscriber."""

from prometheus_client import Counter, Histogram

# Counter for total events received from the stream
events_received = Counter(
    "subscriber_events_received_total",
    "Total events received from stream",
    labelnames=["event_type"],
)

# Counter for total events successfully posted to Slack
events_posted = Counter(
    "subscriber_events_posted_total",
    "Total events posted to Slack",
    labelnames=["event_type"],
)

# Counter for total events that failed processing
events_failed = Counter(
    "subscriber_events_failed_total",
    "Total events that failed processing",
    labelnames=["event_type", "error_type"],
)

# Histogram for event processing latency
event_processing_duration = Histogram(
    "subscriber_event_processing_duration_seconds",
    "Event processing latency",
    labelnames=["event_type"],
)
