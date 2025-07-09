from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from pydantic import BaseModel

from reconcile.utils.ocm.base import (
    OCMClusterServiceLogCreateModel,
)
from reconcile.utils.ocm.clusters import (
    ClusterDetails,
    discover_clusters_by_labels,
)
from reconcile.utils.ocm.labels import Filter
from reconcile.utils.ocm.manifests import (
    create_manifest,
    get_manifest,
    patch_manifest,
)
from reconcile.utils.ocm.service_log import create_service_log
from reconcile.utils.ocm.syncsets import (
    create_syncset,
    get_syncset,
    patch_syncset,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
)

"""
Thin abstractions of reconcile.ocm module to reduce coupling.
"""


class OCMCluster(BaseModel):
    id: str
    external_id: str
    organization_id: str
    subscription_id: str
    is_hcp: bool
    labels: Mapping[str, str]

    @staticmethod
    def from_cluster_details(cluster: ClusterDetails) -> OCMCluster | None:
        labels = {key: label.value for key, label in cluster.labels.labels.items()}
        return OCMCluster(
            id=cluster.ocm_cluster.id,
            external_id=cluster.ocm_cluster.external_id,
            organization_id=cluster.organization_id,
            subscription_id=cluster.ocm_cluster.subscription.id,
            is_hcp=cluster.ocm_cluster.is_rosa_hypershift(),
            labels=labels,
        )


class OCMClient:
    """
    Thin OOP wrapper around OCMBaseClient to avoid function mocking in tests
    """

    def __init__(self, ocm_client: OCMBaseClient):
        self._ocm_client = ocm_client

    def create_syncset(self, cluster_id: str, syncset_map: Mapping) -> None:
        create_syncset(
            ocm_client=self._ocm_client, cluster_id=cluster_id, syncset_map=syncset_map
        )

    def get_syncset(self, cluster_id: str, syncset_id: str) -> Any:
        return get_syncset(
            ocm_client=self._ocm_client, cluster_id=cluster_id, syncset_id=syncset_id
        )

    def patch_syncset(
        self, cluster_id: str, syncset_id: str, syncset_map: Mapping
    ) -> None:
        patch_syncset(
            ocm_client=self._ocm_client,
            cluster_id=cluster_id,
            syncset_id=syncset_id,
            syncset_map=syncset_map,
        )

    def create_manifest(self, cluster_id: str, manifest_map: Mapping) -> None:
        create_manifest(
            ocm_client=self._ocm_client,
            cluster_id=cluster_id,
            manifest_map=manifest_map,
        )

    def get_manifest(self, cluster_id: str, manifest_id: str) -> Any:
        return get_manifest(
            ocm_client=self._ocm_client, cluster_id=cluster_id, manifest_id=manifest_id
        )

    def patch_manifest(
        self, cluster_id: str, manifest_id: str, manifest_map: Mapping
    ) -> None:
        patch_manifest(
            ocm_client=self._ocm_client,
            cluster_id=cluster_id,
            manifest_id=manifest_id,
            manifest_map=manifest_map,
        )

    def discover_clusters_by_labels(self, label_filter: Filter) -> list[OCMCluster]:
        return [
            cluster
            for ocm_cluster in discover_clusters_by_labels(
                ocm_api=self._ocm_client, label_filter=label_filter
            )
            if (cluster := OCMCluster.from_cluster_details(ocm_cluster))
        ]

    def create_service_log(
        self,
        service_log: OCMClusterServiceLogCreateModel,
        dedup_interval: timedelta | None,
    ) -> None:
        create_service_log(
            ocm_api=self._ocm_client,
            service_log=service_log,
            dedup_interval=dedup_interval,
        )
