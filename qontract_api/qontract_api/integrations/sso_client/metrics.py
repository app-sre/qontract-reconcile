"""Prometheus metrics for RHIDP SSO client reconciliation.

Ports the 4 legacy reconcile/rhidp/sso_client/metrics.py metrics to the qontract-api
backend (dashboards/alerts key off these exact names - including the "inital" typo -
so they are preserved as-is).
"""

from prometheus_client import Counter, Gauge

# Matches the legacy integration name label so existing dashboards/alerts keep working.
INTEGRATION_NAME = "rhidp-sso-client"

rhidp_managed_clusters = Gauge(
    "rhidp_managed_clusters",
    "Number of managed clusters per organization.",
    ["integration", "ocm_environment", "org_id"],
)

rhidp_sso_client_number_of_clients = Gauge(
    "rhidp_sso_client_number_of_clients",
    "Number of existing SSO clients.",
    ["integration", "ocm_environment"],
)

rhidp_sso_client_inital_access_token_expiration = Gauge(
    "rhidp_sso_client_inital_access_token_expiration",
    "Gauge for the expiration of the initial access token.",
    ["integration", "ocm_environment", "path"],
)

rhidp_sso_client_reconciled = Counter(
    "rhidp_sso_client_reconciled",
    "Counter for successful reconcile runs.",
    ["integration", "ocm_environment"],
)

rhidp_sso_client_reconcile_errors = Counter(
    "rhidp_sso_client_reconcile_errors",
    "Counter for the failed reconcile runs.",
    ["integration", "ocm_environment"],
)
