"""Prometheus metrics for ldap-groups reconciliation."""

from prometheus_client import Counter

INTEGRATION_NAME = "ldap-groups"

ldap_groups_reconciled = Counter(
    "ldap_groups_reconciled",
    "Counter for successful ldap-groups reconcile runs.",
    ["integration"],
)

ldap_groups_reconcile_errors = Counter(
    "ldap_groups_reconcile_errors",
    "Counter for failed ldap-groups reconcile runs.",
    ["integration"],
)
