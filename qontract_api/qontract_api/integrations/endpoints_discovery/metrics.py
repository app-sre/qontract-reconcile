"""Prometheus metrics for endpoints-discovery reconciliation."""

from prometheus_client import Gauge

# Must match the legacy integration name so existing dashboards keep
# aggregating across the old and new integration during rollout.
INTEGRATION_NAME = "endpoints-discovery"

endpoints_discovery_apps_with_changes = Gauge(
    "endpoints_discovery_apps_with_changes",
    "Applications with at least one endpoint change in the last run.",
    ["integration"],
)
