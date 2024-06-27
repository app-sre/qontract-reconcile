import base64
from collections.abc import Iterable, Mapping
from typing import Any
from unittest.mock import (
    MagicMock,
    create_autospec,
)

from reconcile.dynatrace_token_provider.ocm import Cluster, OCMClient
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated, DynatraceClient


def tobase64(s: str) -> str:
    data_bytes = s.encode("utf-8")
    encoded = base64.b64encode(data_bytes)
    return encoded.decode("utf-8")


def build_syncset(
    operator_token: DynatraceAPITokenCreated,
    ingestion_token: DynatraceAPITokenCreated,
    tenant_id: str,
    with_id: bool,
) -> dict:
    syncset = {
        "kind": "SyncSet",
        "resources": [
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {
                    "name": "dynatrace-token-dtp",
                    "namespace": "dynatrace",
                },
                "data": {
                    "apiUrl": tobase64(f"https://{tenant_id}.live.dynatrace.com/api"),
                    "dataIngestTokenId": tobase64(ingestion_token.id),
                    "dataIngestToken": tobase64(ingestion_token.token),
                    "apiTokenId": tobase64(operator_token.id),
                    "apiToken": tobase64(operator_token.token),
                },
            }
        ],
    }
    if with_id:
        syncset["id"] = "ext-dynatrace-tokens-dtp"
    return syncset


def build_ocm_client(
    discover_clusters_by_labels: Iterable[Cluster], get_syncset: Mapping[str, Mapping]
) -> OCMClient:
    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_labels.return_value = discover_clusters_by_labels

    def get_syncset_side_effect(cluster_id: str, syncset_id: str) -> Any:
        return get_syncset.get(cluster_id)

    mock_get_syncset = MagicMock(side_effect=get_syncset_side_effect)
    ocm_client.get_syncset = mock_get_syncset
    return ocm_client


def build_dynatrace_client(
    create_api_token: Mapping[str, DynatraceAPITokenCreated],
    existing_token_ids: set[str],
) -> DynatraceClient:
    dynatrace_client = create_autospec(spec=DynatraceClient)

    def create_api_token_side_effect(
        name: str, scopes: Iterable[str]
    ) -> DynatraceAPITokenCreated:
        return create_api_token.get(
            name, DynatraceAPITokenCreated(token="dummy", id="dummy")
        )

    mock_create_api_token = MagicMock(side_effect=create_api_token_side_effect)
    dynatrace_client.create_api_token = mock_create_api_token
    dynatrace_client.get_token_ids_for_name_prefix.return_value = existing_token_ids

    return dynatrace_client
