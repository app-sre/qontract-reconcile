"""Prometheus metrics for OCM groups reconciliation.

Ports the legacy reconcile/ocm_groups.py integration's reconcile counters to the
qontract-api backend (dashboards/alerts key off these exact names, preserved as-is).
"""

from prometheus_client import Counter, Gauge

INTEGRATION_NAME = "ocm-groups"

ocm_groups_reconciled = Counter(
    "ocm_groups_reconciled",
    "Counter for successful reconcile runs.",
    ["integration", "ocm_environment"],
)

ocm_groups_reconcile_errors = Counter(
    "ocm_groups_reconcile_errors",
    "Counter for the failed reconcile runs.",
    ["integration", "ocm_environment"],
)

ocm_groups_managed_clusters = Gauge(
    "ocm_groups_managed_clusters",
    "Number of managed clusters per cluster name.",
    ["integration", "ocm_environment", "cluster"],
)
