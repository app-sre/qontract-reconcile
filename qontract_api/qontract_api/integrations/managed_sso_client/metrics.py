"""Prometheus metrics for managed-sso-client reconciliation."""

from prometheus_client import Counter, Gauge

INTEGRATION_NAME = "managed-sso-client"

managed_sso_clients_managed = Gauge(
    "managed_sso_clients_managed",
    "Number of managed SSO clients currently tracked in Vault.",
    ["integration"],
)

managed_sso_client_reconciled = Counter(
    "managed_sso_client_reconciled",
    "Counter for successful reconcile runs.",
    ["integration"],
)

managed_sso_client_reconcile_errors = Counter(
    "managed_sso_client_reconcile_errors",
    "Counter for the failed reconcile runs.",
    ["integration"],
)

managed_sso_client_token_persist_failures = Counter(
    "managed_sso_client_token_persist_failures",
    "Counter for updates where Keycloak rotated the registration access token "
    "but persisting it to Vault failed - Keycloak and Vault are now "
    "inconsistent for that client and it will not self-heal on the next "
    "reconcile. Any non-zero rate here needs manual investigation.",
    ["integration"],
)
