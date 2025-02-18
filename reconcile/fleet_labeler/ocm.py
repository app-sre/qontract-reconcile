from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import (
    get_cluster_labels_for_cluster_id,
)
from reconcile.utils.ocm.search_filters import Filter, FilterMode
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
)

"""
Thin abstractions of reconcile.ocm module to reduce coupling.
"""


class Cluster(BaseModel):
    cluster_id: str
    server_url: str
    name: str
    subscription_labels: dict[str, str]

    @staticmethod
    def from_cluster_details(cluster: ClusterDetails) -> Cluster:
        server_url = (
            cluster.ocm_cluster.console.url if cluster.ocm_cluster.console else ""
        )

        return Cluster(
            cluster_id=cluster.ocm_cluster.id,
            server_url=server_url,
            name=cluster.ocm_cluster.name,
            subscription_labels={
                label.key: label.value
                for label in cluster.subscription_labels.labels.values()
            },
        )


class OCMClientConfig(BaseModel):
    """
    OCMOrg does not have the required structure to comply with OCMBaseClient Protocol.
    This class provides a concrete implementation for the required Protocol.
    """

    url: str
    access_token_client_id: str
    access_token_url: str
    access_token_client_secret: VaultSecret


class OCMClient:
    """
    Thin OOP wrapper around OCMBaseClient to avoid function mocking in tests and reduce coupling.
    """

    def __init__(self, ocm_client: OCMBaseClient):
        self._ocm_client = ocm_client

    def discover_clusters_by_labels(self, labels: Mapping[str, str]) -> list[Cluster]:
        label_filter = Filter(mode=FilterMode.AND).eq("type", "Subscription")
        for key in labels:
            label_filter = label_filter.eq("Key", key)
        # TODO: This throws 400 bad request
        # for k, v in labels.items():
        #     label_filter = label_filter.eq(k, v)
        return [
            Cluster.from_cluster_details(cluster)
            for cluster in discover_clusters_by_labels(
                ocm_api=self._ocm_client, label_filter=label_filter
            )
        ]

    def get_cluster_labels(self, cluster_id: str) -> dict[str, str]:
        return get_cluster_labels_for_cluster_id(self._ocm_client, cluster_id)
