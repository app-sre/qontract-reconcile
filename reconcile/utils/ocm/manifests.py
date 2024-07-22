from collections.abc import Generator, Mapping
from dataclasses import dataclass
from typing import Any

from reconcile.utils.ocm_base_client import OCMBaseClient


@dataclass
class Manifest:
    def __init__(self, cluster_id: str):
        self.href = f"/api/clusters_mgmt/v1/clusters/{cluster_id}/external_configuration/manifests"

    href: str


def get_manifests(
    ocm_client: OCMBaseClient, cluster_id: str
) -> Generator[dict[str, Any], None, None]:
    manifest = Manifest(cluster_id)
    return ocm_client.get_paginated(api_path=manifest.href)


def get_manifest(ocm_client: OCMBaseClient, cluster_id: str, manifest_id: str) -> Any:
    manifest = Manifest(cluster_id)
    return ocm_client.get(api_path=manifest.href + "/" + manifest_id)


def create_manifest(
    ocm_client: OCMBaseClient, cluster_id: str, manifest_map: Mapping
) -> None:
    manifest = Manifest(cluster_id)
    ocm_client.post(api_path=manifest.href, data=manifest_map)


def patch_manifest(
    ocm_client: OCMBaseClient, cluster_id: str, manifest_id: str, manifest_map: Mapping
) -> None:
    manifest = Manifest(cluster_id)
    ocm_client.patch(api_path=manifest.href + "/" + manifest_id, data=manifest_map)
