"""Prometheus metrics shared across RHIDP integrations (sso_client, ocm_oidc_idp).

rhidp_managed_clusters is emitted by both integrations (with different `integration`
label values) - it must be a single shared metric object, since prometheus_client
raises on registering the same metric name twice.
"""

from prometheus_client import Gauge

rhidp_managed_clusters = Gauge(
    "rhidp_managed_clusters",
    "Number of managed clusters per organization.",
    ["integration", "ocm_environment", "org_id"],
)
