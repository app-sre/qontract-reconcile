"""Metrics for qontract-utils."""

from prometheus_client.core import Counter

slack_request = Counter(
    name="qontract_reconcile_slack_request_total",
    documentation="Number of calls made to Slack API",
    labelnames=["resource", "verb"],
)
