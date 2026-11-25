"""Prometheus metrics for OCM machine pool reconciliation.

The integration name label is the LEGACY integration's name (ocm-machine-pools,
not ocm-machine-pools-api) so existing dashboards/alerts keep aggregating
correctly across the old and new integrations during the rollout.
"""

from prometheus_client import Counter

INTEGRATION_NAME = "ocm-machine-pools"

ocm_machine_pools_reconciled = Counter(
    "ocm_machine_pools_reconciled",
    "Counter for successful reconcile runs.",
    ["integration", "ocm_environment"],
)

ocm_machine_pools_reconcile_errors = Counter(
    "ocm_machine_pools_reconcile_errors",
    "Counter for the failed reconcile runs.",
    ["integration", "ocm_environment"],
)
