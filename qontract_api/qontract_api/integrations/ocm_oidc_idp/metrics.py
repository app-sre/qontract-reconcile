"""Prometheus metrics for OCM OIDC identity provider reconciliation.

Ports the 2 legacy reconcile/rhidp/ocm_oidc_idp/metrics.py counters to the
qontract-api backend (dashboards/alerts key off these exact names, preserved as-is).
rhidp_managed_clusters is shared with sso_client - see qontract_api.rhidp.metrics.
"""

from prometheus_client import Counter

from qontract_api.rhidp.metrics import rhidp_managed_clusters

__all__ = ["rhidp_managed_clusters"]

# Matches the legacy integration name label so existing dashboards/alerts keep working.
INTEGRATION_NAME = "rhidp-ocm-oidc-idp"

rhidp_ocm_oidc_idp_reconciled = Counter(
    "rhidp_ocm_oidc_idp_reconciled",
    "Counter for successful reconcile runs.",
    ["integration", "ocm_environment"],
)

rhidp_ocm_oidc_idp_reconcile_errors = Counter(
    "rhidp_ocm_oidc_idp_reconcile_errors",
    "Counter for the failed reconcile runs.",
    ["integration", "ocm_environment"],
)
