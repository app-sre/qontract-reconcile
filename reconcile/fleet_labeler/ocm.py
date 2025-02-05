from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import (
    get_cluster_labels_for_cluster_id,
    subscription_label_filter,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
)
from reconcile.utils.secret_reader import HasSecret

"""
Thin abstractions of reconcile.ocm module to reduce coupling.
"""


class Cluster(BaseModel):
    cluster_id: str
    server_url: str
    name: str

    @staticmethod
    def from_cluster_details(cluster: ClusterDetails) -> Cluster:
        server_url = (
            cluster.ocm_cluster.console.url if cluster.ocm_cluster.console else ""
        )

        return Cluster(
            cluster_id=cluster.ocm_cluster.id,
            server_url=server_url,
            name=cluster.ocm_cluster.name,
        )


class OCMClientConfig(BaseModel):
    url: str
    access_token_client_id: str
    access_token_url: str
    access_token_client_secret: HasSecret

    class Config:
        arbitrary_types_allowed = True


class OCMClient:
    """
    Thin OOP wrapper around OCMBaseClient to avoid function mocking in tests
    """

    def __init__(self, ocm_client: OCMBaseClient):
        self._ocm_client = ocm_client

    def discover_clusters_by_labels(self, labels: Mapping[str, str]) -> list[Cluster]:
        label_filter = subscription_label_filter()
        for label in labels:
            label_filter = label_filter.like("key", label)

        clusters = []
        for cluster in discover_clusters_by_labels(
            ocm_api=self._ocm_client, label_filter=label_filter
        ):
            subscription_labels = {
                label.key: label.value
                for label in cluster.subscription_labels.labels.values()
            }
            if labels.items() <= subscription_labels.items():
                clusters.append(Cluster.from_cluster_details(cluster))
        return clusters

    def get_cluster_labels(self, cluster_id: str) -> dict[str, str]:
        return get_cluster_labels_for_cluster_id(self._ocm_client, cluster_id)
