from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import (
    add_label,
    get_cluster_labels_for_cluster_id,
    update_label,
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
    subscription_id: str
    server_url: str
    name: str
    subscription_labels: dict[str, str]

    @staticmethod
    def from_cluster_details(cluster: ClusterDetails) -> Cluster:
        console_url = (
            cluster.ocm_cluster.console.url if cluster.ocm_cluster.console else ""
        )
        api_url = cluster.ocm_cluster.api_url or ""
        server_url = api_url or console_url or ""

        return Cluster(
            cluster_id=cluster.ocm_cluster.id,
            subscription_id=cluster.ocm_cluster.subscription.id,
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

    def discover_clusters_by_labels(
        self, labels: Mapping[str, str], managed_prefix: str
    ) -> list[Cluster]:
        label_filter = Filter(mode=FilterMode.AND).eq("type", "Subscription")
        for key in labels:
            label_filter = label_filter.eq("Key", key)
        desired_labels_filter = (
            Filter(mode=FilterMode.AND)
            .eq("type", "Subscription")
            .like(
                "key",
                f"{managed_prefix}.%",
            )
        )
        # Note, that discover_clusters_by_labels() only fetches labels that are matching the filter!
        # However, to understand current state, we also want to know the labels under managed_prefix.
        # I.e., we need a fetch condition such as:
        # ("{managed_prefix}.%") OR ("{key1_filter}" AND "{key2_filter}" ....)
        # The above returns also clusters that do not fit the match label.
        # I.e., we must filter the result on client side.
        # TODO: do this in utils.ocm module
        desired_filter = label_filter | desired_labels_filter
        return [
            Cluster.from_cluster_details(cluster)
            for cluster in discover_clusters_by_labels(
                ocm_api=self._ocm_client, label_filter=desired_filter
            )
        ]

    def get_cluster_labels(self, cluster_id: str) -> dict[str, str]:
        return get_cluster_labels_for_cluster_id(self._ocm_client, cluster_id)

    def add_subscription_label(
        self, subscription_id: str, key: str, value: str
    ) -> None:
        # TODO: move href into a utils function
        add_label(
            ocm_api=self._ocm_client,
            label_container_href=f"/api/accounts_mgmt/v1/subscriptions/{subscription_id}/labels",
            label=key,
            value=value,
        )

    def update_subscription_label(
        self, subscription_id: str, key: str, value: str
    ) -> None:
        # TODO: move href into a utils function
        update_label(
            ocm_api=self._ocm_client,
            label_container_href=f"/api/accounts_mgmt/v1/subscriptions/{subscription_id}/labels",
            label=key,
            value=value,
        )
