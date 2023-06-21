from collections import defaultdict
from typing import (
    Any,
    Callable,
    Optional,
)

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.rhidp.clusters import (
    ClusterAuthOIDCV1,
    ClusterV1,
    OpenShiftClusterManagerV1,
)
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


def build_cluster_obj(
    ocm_env: OCMEnvironment,
    cluster: ClusterDetails,
    auth_name: str,
    auth_issuer_url: str,
) -> ClusterV1:
    return ClusterV1(
        name=cluster.ocm_cluster.name,
        consoleUrl=cluster.ocm_cluster.console.url,
        ocm=OpenShiftClusterManagerV1(
            name="",
            environment=ocm_env,
            orgId=cluster.organization_id,
            # unused values
            accessTokenClientId=None,
            accessTokenClientSecret=None,
            accessTokenUrl=None,
            blockedVersions=None,
            sectors=None,
        ),
        auth=[
            ClusterAuthOIDCV1(
                service="oidc",
                name=auth_name,
                issuer=auth_issuer_url,
                # stick with the defaults
                claims=None,
            )
        ],
        # unused values
        upgradePolicy=None,
        disable=None,
    )


def get_clusters(
    integration_name: str, query_func: Callable, default_issuer_url: str
) -> list[ClusterV1]:
    """Get all clusters from AppInterface."""
    data = cluster_query(query_func, variables={})
    clusters: list[ClusterV1] = []

    for c in data.clusters or []:
        if not integration_is_enabled(integration_name, c):
            # integration disabled for this particular cluster
            continue
        if c.ocm is None:
            # no ocm relation
            continue
        if not [auth for auth in c.auth if isinstance(auth, ClusterAuthOIDCV1)]:
            # no OIDC auth
            continue
        for auth in c.auth:
            if isinstance(auth, ClusterAuthOIDCV1) and not auth.issuer:
                auth.issuer = default_issuer_url
        clusters.append(c)
    return clusters


def cluster_vault_secret_id(org_id: str, cluster_name: str, auth_name: str) -> str:
    """Returns the vault secret id for the given cluster."""
    return f"{cluster_name}-{org_id}-{auth_name}"


def cluster_vault_secret(
    vault_input_path: str,
    org_id: Optional[str] = None,
    cluster_name: Optional[str] = None,
    auth_name: Optional[str] = None,
    vault_secret_id: Optional[str] = None,
) -> dict[str, Any]:
    """Returns the vault secret path for the given cluster."""
    if not vault_secret_id and (org_id and cluster_name and auth_name):
        cid = cluster_vault_secret_id(org_id, cluster_name, auth_name)
    elif vault_secret_id:
        cid = vault_secret_id
    else:
        raise ValueError(
            "vault_secret_id or org_id, cluster_name and auth_name must be provided"
        )
    return {"path": f"{vault_input_path.rstrip('/')}/{cid}"}
