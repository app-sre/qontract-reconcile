from collections import Counter
from collections.abc import (
    Iterable,
    MutableMapping,
)
from enum import Enum
from typing import Any
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    root_validator,
)

from reconcile.gql_definitions.common.ocm_environments import (
    query as ocm_environment_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.rhidp.metrics import RhIdpClusterCounter
from reconcile.utils import gql
from reconcile.utils.metrics import MetricsContainer
from reconcile.utils.ocm.base import OCMCluster
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import subscription_label_filter
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
from reconcile.utils.ocm_base_client import OCMBaseClient

# Generates label keys for rhidp, compliant with the naming schema defined in
# https://service.pages.redhat.com/dev-guidelines/docs/sre-capabilities/framework/ocm-labels/
RHIDP_NAMESPACE_LABEL_KEY = sre_capability_label_key("rhidp")
STATUS_LABEL_KEY = sre_capability_label_key("rhidp", "status")
ISSUER_LABEL_KEY = sre_capability_label_key("rhidp", "issuer")
AUTH_NAME_LABEL_KEY = sre_capability_label_key("rhidp", "name")


class StatusValue(str, Enum):
    # rhidp and oidc are enabled
    ENABLED = "enabled"
    # rhidp and oidc are disabled
    DISABLED = "disabled"
    # rhidp is enabled and oidc will delete all other configured idps
    ENFORCED = "enforced"
    # rhidp is enabled and oidc is skipped
    RHIDP_ONLY = "sso-client-only"


class ClusterAuth(BaseModel):
    name: str
    issuer: str
    status: str

    @root_validator
    def name_no_spaces(  # pylint: disable=no-self-argument
        cls, values: MutableMapping[str, Any]
    ) -> MutableMapping[str, Any]:
        values["name"] = values["name"].replace(" ", "-")
        return values

    @property
    def rhidp_enabled(self) -> bool:
        return self.status != StatusValue.DISABLED.value

    @property
    def oidc_enabled(self) -> bool:
        return self.status not in (
            StatusValue.DISABLED.value,
            StatusValue.RHIDP_ONLY.value,
        )

    @property
    def enforced(self) -> bool:
        return self.status == StatusValue.ENFORCED.value


class Cluster(BaseModel):
    ocm_cluster: OCMCluster
    auth: ClusterAuth
    organization_id: str

    @property
    def name(self) -> str:
        return self.ocm_cluster.name

    @property
    def console_url(self) -> str | None:
        return self.ocm_cluster.console.url if self.ocm_cluster.console else None


def discover_clusters(
    ocm_api: OCMBaseClient, org_ids: set[str] | None
) -> list[ClusterDetails]:
    """Discover all clusters that are part of the RHIDP service."""
    clusters = discover_clusters_by_labels(
        ocm_api=ocm_api,
        label_filter=subscription_label_filter().like(
            "key", f"{RHIDP_NAMESPACE_LABEL_KEY}%"
        ),
    )

    # filter by org if org_id is specified
    return [c for c in clusters if org_ids is None or c.organization_id in org_ids]


def build_cluster_objects(
    cluster_details: Iterable[ClusterDetails],
    default_auth_name: str,
    default_issuer_url: str,
) -> list[Cluster]:
    return [
        Cluster(
            ocm_cluster=cluster.ocm_cluster,
            auth=ClusterAuth(
                name=cluster.labels.get_label_value(AUTH_NAME_LABEL_KEY)
                or default_auth_name,
                issuer=cluster.labels.get_label_value(ISSUER_LABEL_KEY)
                or default_issuer_url,
                # "rhidp" label is deprecated, but we still need to support it
                # "rhidp.status" is the new label
                status=cluster.labels.get_label_value(RHIDP_NAMESPACE_LABEL_KEY)
                or cluster.labels.get_label_value(STATUS_LABEL_KEY)
                or StatusValue.DISABLED.value,
            ),
            organization_id=cluster.organization_id,
        )
        for cluster in cluster_details
        # we can't calculate the redirect url w/o a console url
        if cluster.ocm_cluster.console
    ]


def cluster_vault_secret_id(
    org_id: str, cluster_name: str, auth_name: str, issuer_url: str
) -> str:
    """Returns the vault secret id for the given cluster."""
    url = urlparse(issuer_url)
    return f"{cluster_name}-{org_id}-{auth_name}-{url.hostname}"


def cluster_vault_secret(
    vault_input_path: str,
    org_id: str | None = None,
    cluster_name: str | None = None,
    auth_name: str | None = None,
    issuer_url: str | None = None,
    vault_secret_id: str | None = None,
) -> VaultSecret:
    """Returns the vault secret path for the given cluster."""
    if not vault_secret_id and (org_id and cluster_name and auth_name and issuer_url):
        cid = cluster_vault_secret_id(org_id, cluster_name, auth_name, issuer_url)
    elif vault_secret_id:
        cid = vault_secret_id
    else:
        raise ValueError(
            "vault_secret_id or org_id, cluster_name, auth_name, and issuer_url must be provided"
        )
    return VaultSecret(
        path=f"{vault_input_path.rstrip('/')}/{cid}",
        field="",
        version=None,
        format=None,
    )


def expose_base_metrics(
    metrics_container: MetricsContainer,
    integration_name: str,
    ocm_environment: str,
    clusters: Iterable[Cluster],
) -> None:
    clusters_per_org: Counter[str] = Counter()
    for cluster in clusters:
        clusters_per_org[cluster.organization_id] += 1

    # clusters per org counter
    for org_id, count in clusters_per_org.items():
        metrics_container.set_gauge(
            RhIdpClusterCounter(
                integration=integration_name,
                ocm_environment=ocm_environment,
                org_id=org_id,
            ),
            value=count,
        )


def get_ocm_environments(env_name: str | None) -> list[OCMEnvironment]:
    return ocm_environment_query(
        gql.get_api().query,
        variables={"name": env_name} if env_name else None,
    ).environments
