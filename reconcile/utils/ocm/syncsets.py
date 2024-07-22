from collections.abc import Generator, Mapping
from dataclasses import dataclass
from typing import Any

from reconcile.utils.ocm_base_client import OCMBaseClient


@dataclass
class SyncSet:
    def __init__(self, cluster_id: str):
        self.href = f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/syncsets"

    href: str


def get_syncsets(
    ocm_client: OCMBaseClient, cluster_id: str
) -> Generator[dict[str, Any], None, None]:
    syncset = SyncSet(cluster_id)
    return ocm_client.get_paginated(api_path=syncset.href)


def get_syncset(ocm_client: OCMBaseClient, cluster_id: str, syncset_id: str) -> Any:
    syncset = SyncSet(cluster_id)
    return ocm_client.get(api_path=syncset.href + "/" + syncset_id)


def create_syncset(
    ocm_client: OCMBaseClient, cluster_id: str, syncset_map: Mapping
) -> None:
    syncset = SyncSet(cluster_id)
    ocm_client.post(api_path=syncset.href, data=syncset_map)


def patch_syncset(
    ocm_client: OCMBaseClient, cluster_id: str, syncset_id: str, syncset_map: Mapping
) -> None:
    syncset = SyncSet(cluster_id)
    ocm_client.patch(api_path=syncset.href + "/" + syncset_id, data=syncset_map)
