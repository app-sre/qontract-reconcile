import base64
from collections.abc import Iterable, Mapping
from typing import Any
from unittest.mock import (
    MagicMock,
    Mock,
    create_autospec,
)

from reconcile.dynatrace_token_provider.integration import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.dynatrace_token_provider.model import DynatraceAPIToken, K8sSecret
from reconcile.dynatrace_token_provider.ocm import OCMClient, OCMCluster
from reconcile.utils.dynatrace.client import DynatraceAPITokenCreated, DynatraceClient
from reconcile.utils.openshift_resource import (
    QONTRACT_ANNOTATION_INTEGRATION,
    QONTRACT_ANNOTATION_INTEGRATION_VERSION,
)

REGIONAL_TENANT_KEY = "sre-capabilities.dtp.v3.regional.tenant"
SLO_TENANT_KEY = "sre-capabilities.dtp.v3.slo.tenant"


def tobase64(s: str) -> str:
    data_bytes = s.encode("utf-8")
    encoded = base64.b64encode(data_bytes)
    return encoded.decode("utf-8")


def _build_secret_data(
    secrets: Iterable[K8sSecret],
) -> list[dict[str, Any]]:
    secrets_data: list[dict[str, Any]] = []
    for secret in secrets:
        data: dict[str, str] = {
            "apiUrl": tobase64(secret.dt_api_url),
        }
        for token in secret.tokens:
            data[token.secret_key] = tobase64(token.token)
            data[f"{token.secret_key}Id"] = tobase64(token.id)
        secrets_data.append({
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {
                "name": secret.secret_name,
                "namespace": secret.namespace_name,
                "annotations": {
                    QONTRACT_ANNOTATION_INTEGRATION: QONTRACT_INTEGRATION,
                    QONTRACT_ANNOTATION_INTEGRATION_VERSION: QONTRACT_INTEGRATION_VERSION,
                },
            },
            "data": data,
        })
    return secrets_data


def build_k8s_secret(
    tokens: Iterable[DynatraceAPIToken],
    tenant_id: str = "dt_tenant_a",
    secret_name: str = "dynatrace-token-dtp",
    namespace_name: str = "dynatrace",
) -> K8sSecret:
    return K8sSecret(
        secret_name=secret_name,
        namespace_name=namespace_name,
        tokens=tokens,
        dt_api_url=f"https://{tenant_id}.live.dynatrace.com/api",
    )


def build_syncset(
    secrets: Iterable[K8sSecret],
    with_id: bool,
) -> dict:
    secrets_data = _build_secret_data(
        secrets=secrets,
    )
    syncset = {
        "kind": "SyncSet",
        "resources": secrets_data,
    }
    if with_id:
        syncset["id"] = "ext-dynatrace-tokens-dtp"
    return syncset


def build_manifest(
    secrets: Iterable[K8sSecret],
    with_id: bool,
) -> dict:
    secrets_data = _build_secret_data(
        secrets=secrets,
    )
    manifest = {
        "kind": "Manifest",
        "workloads": secrets_data,
    }
    if with_id:
        manifest["id"] = "ext-dynatrace-tokens-dtp"
    return manifest


def build_ocm_client(
    discover_clusters_by_labels: Iterable[OCMCluster],
    get_syncset: Mapping[str, Mapping],
    get_manifest: Mapping[str, Mapping],
) -> Mock:
    ocm_client = create_autospec(spec=OCMClient)
    ocm_client.discover_clusters_by_labels.return_value = discover_clusters_by_labels

    def get_syncset_side_effect(cluster_id: str, syncset_id: str) -> Any:
        return get_syncset.get(cluster_id)

    def get_manifest_side_effect(cluster_id: str, manifest_id: str) -> Any:
        return get_manifest.get(cluster_id)

    mock_get_syncset = MagicMock(side_effect=get_syncset_side_effect)
    ocm_client.get_syncset = mock_get_syncset

    mock_get_manifest = MagicMock(side_effect=get_manifest_side_effect)
    ocm_client.get_manifest = mock_get_manifest

    return ocm_client


def build_dynatrace_client(
    create_api_token: Mapping[str, DynatraceAPITokenCreated],
    existing_token_ids: dict[str, str],
) -> Mock:
    dynatrace_client = create_autospec(spec=DynatraceClient)

    def create_api_token_side_effect(
        name: str, scopes: Iterable[str]
    ) -> DynatraceAPITokenCreated:
        if name not in create_api_token:
            raise ValueError(f"token {name=} not found in dynatrace_mock")
        return create_api_token[name]

    mock_create_api_token = MagicMock(side_effect=create_api_token_side_effect)
    dynatrace_client.create_api_token = mock_create_api_token
    dynatrace_client.get_token_ids_map_for_name_prefix.return_value = existing_token_ids

    return dynatrace_client
