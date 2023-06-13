from collections import defaultdict
from typing import (
    Callable,
    Optional,
)

from reconcile.gql_definitions.rhidp.clusters import ClusterV1
from reconcile.gql_definitions.rhidp.clusters import query as cluster_query
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm_base_client import OCMBaseClient

# Generates label keys for rhidp, compliant with the naming schema defined in
# https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
RHIDP_LABEL_KEY = sre_capability_label_key("rhidp")


def discover_clusters(
    ocm_api: OCMBaseClient, org_ids: Optional[set[str]] = None
) -> dict[str, list[ClusterDetails]]:
    """Discover all clusters that are part of the RHIDP service."""
    clusters = discover_clusters_by_labels(
        ocm_api=ocm_api,
        label_filter=subscription_label_filter()
        .eq("key", RHIDP_LABEL_KEY)
        .eq("value", "enabled"),
    )

    # group by org and filter if org_id is specified
    clusters_by_org: dict[str, list[ClusterDetails]] = defaultdict(list)
    for c in clusters:
        passed_ocm_filters = org_ids is None or c.organization_id in org_ids
        if passed_ocm_filters:
            clusters_by_org[c.organization_id].append(c)

    return clusters_by_org


def get_clusters(integration_name: str, query_func: Callable) -> list[ClusterV1]:
    """Get all clusters from AppInterface."""
    data = cluster_query(query_func, variables={})
    return [
        c
        for c in data.clusters or []
        if integration_is_enabled(integration_name, c) and c.ocm is not None
    ]
