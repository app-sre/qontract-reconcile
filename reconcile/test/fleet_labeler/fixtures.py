from collections.abc import Iterable
from unittest.mock import (
    create_autospec,
)

from reconcile.fleet_labeler.ocm import Cluster, OCMClient


def build_ocm_client(
    discover_clusters_by_labels: Iterable[Cluster],
) -> OCMClient:
    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_labels.return_value = discover_clusters_by_labels
    return ocm_client


def build_cluster(
    subscription_labels: dict[str, str] | None,
    cluster_id: str = "cluster_id",
    name: str = "cluster_name",
    server_url: str = "https://api.test.com",
) -> Cluster:
    if not subscription_labels:
        subscription_labels = {"test": "true"}
    return Cluster(
        cluster_id=cluster_id,
        name=name,
        server_url=server_url,
        subscription_labels=subscription_labels,
    )
