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
from reconcile.utils.ocm.sre_capability_labels import sre_capability_label_key
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

DTP_TENANT_LABEL = sre_capability_label_key("dtp", "tenant")
DTP_SPEC_LABEL = sre_capability_label_key("dtp", "token-spec")
DTP_LABEL_SEARCH = sre_capability_label_key("dtp", "%")


class Cluster(BaseModel):
    id: str
    external_id: str
    organization_id: str
    dt_tenant: str
    token_spec_name: str
    is_hcp: bool

    @staticmethod
    def from_cluster_details(cluster: ClusterDetails) -> Cluster:
        dt_tenant = cluster.labels.get_label_value(DTP_TENANT_LABEL)
        token_spec_name = cluster.labels.get_label_value(DTP_SPEC_LABEL)
        if not token_spec_name:
            """
            We want to stay backwards compatible.
            Earlier version of DTP did not set a value for the label.
            We fall back to a default token in that case.

            Long-term, we want to remove this behavior.
            """
            token_spec_name = "hypershift-management-cluster-v1"
        return Cluster(
            id=cluster.ocm_cluster.id,
            external_id=cluster.ocm_cluster.external_id,
            organization_id=cluster.organization_id,
            dt_tenant=dt_tenant,
            token_spec_name=token_spec_name,
            is_hcp=cluster.ocm_cluster.is_rosa_hypershift(),
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

    def discover_clusters_by_labels(self, label_filter: Filter) -> list[Cluster]:
        return [
            Cluster.from_cluster_details(cluster)
            for cluster in discover_clusters_by_labels(
                ocm_api=self._ocm_client, label_filter=label_filter
            )
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
