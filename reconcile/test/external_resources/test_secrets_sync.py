import copy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, create_autospec

from pytest import MonkeyPatch, fixture

from reconcile.external_resources.meta import (
    QONTRACT_INTEGRATION,
    QONTRACT_INTEGRATION_VERSION,
)
from reconcile.external_resources.secrets_sync import (
    SECRET_UPDATED_AT,
    SecretHelper,
    VaultSecretsReconciler,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec
from reconcile.utils.openshift_resource import OpenshiftResource, ResourceInventory
from reconcile.utils.secret_reader import SecretReaderBase


@dataclass
class _FakeCluster:
    name: str


def _reconciler() -> VaultSecretsReconciler:
    return VaultSecretsReconciler(
        ri=ResourceInventory(),
        secrets_reader=create_autospec(SecretReaderBase),
        vault_path="test-path",
        thread_pool_size=1,
        dry_run=True,
    )


def _spec(cluster: str, namespace: str, cluster_admin: bool) -> ExternalResourceSpec:
    namespace_data: dict = {"name": namespace, "cluster": {"name": cluster}}
    if cluster_admin:
        namespace_data["clusterAdmin"] = True
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "provisioner"},
        resource={"identifier": f"{namespace}-id", "provider": "vpc-endpoint-service"},
        namespace=namespace_data,
    )


def test_init_ocmap_requests_privileged_client_for_cluster_admin_namespace(
    monkeypatch: MonkeyPatch,
) -> None:
    """A namespace with clusterAdmin: true (e.g. a protected namespace like
    openshift-ingress) must get a privileged OC client - otherwise the
    secret sync 403s, since the standard dedicated-admin token is forbidden
    there."""
    reconciler = _reconciler()
    specs = [
        _spec("cluster-a", "protected-ns", cluster_admin=True),
        _spec("cluster-b", "regular-ns", cluster_admin=False),
    ]

    captured_namespaces: list[Any] = []

    def fake_get_clusters_minimal() -> list[_FakeCluster]:
        return [_FakeCluster("cluster-a"), _FakeCluster("cluster-b")]

    def fake_init_oc_map_from_namespaces(namespaces: Any, **_kwargs: Any) -> str:
        captured_namespaces.extend(namespaces)
        return "fake-ocmap"

    monkeypatch.setattr(
        "reconcile.external_resources.secrets_sync.get_clusters_minimal",
        fake_get_clusters_minimal,
    )
    monkeypatch.setattr(
        "reconcile.external_resources.secrets_sync.init_oc_map_from_namespaces",
        fake_init_oc_map_from_namespaces,
    )

    ocmap = reconciler._init_ocmap(specs)

    assert ocmap == "fake-ocmap"
    assert reconciler._privileged_namespaces == {("cluster-a", "protected-ns")}
    admin_by_cluster = {ns.cluster.name: ns.cluster_admin for ns in captured_namespaces}
    assert admin_by_cluster == {"cluster-a": True, "cluster-b": False}


def test_apply_action_threads_privileged_flag_into_apply_options(
    monkeypatch: MonkeyPatch,
) -> None:
    reconciler = _reconciler()
    captured_options: list[Any] = []

    def fake_apply_action(
        oc_map: Any,
        ri: Any,
        cluster: Any,
        namespace: Any,
        resource_type: Any,
        resource: Any,
        options: Any,
    ) -> None:
        captured_options.append(options)

    monkeypatch.setattr(
        "reconcile.external_resources.secrets_sync.apply_action",
        fake_apply_action,
    )

    fake_item = MagicMock(spec=OpenshiftResource)
    fake_item.name = "secret-a"

    reconciler.apply_action(
        ocmap=MagicMock(),
        cluster="cluster-a",
        namespace="protected-ns",
        items=[fake_item],
        privileged=True,
    )

    assert captured_options[-1].privileged is True


@fixture
def resource() -> OpenshiftResource:
    return OpenshiftResource(
        body={
            "apiVersion": "v1",
            "kind": "Secret",
            "type": "Opaque",
            "data": {
                "attribute": "cvalue",
            },
            "metadata": {
                "annotations": {
                    "external-resources/identifier": "rds-test-01",
                    "external-resources/provider": "rds",
                    "external-resources/provision_provider": "aws",
                    "external-resources/provisioner_name": "app-int-example-01",
                    "external-resources/updated_at": "2024-05-29T18:44:46",
                    "qontract.caller_name": "app-int-example-01",
                    "qontract.integration": "external_resources",
                    "qontract.integration_version": "0.1.0",
                    "qontract.recycle": "true",
                    "qontract.sha256sum": "b8bb13e6548bc418d4ea9c01d0d040b6150558f9ba2bb59ea95fd401585adf76",
                    "qontract.update": "2024-05-29T16:44:37",
                },
                "name": "creds",
                "namespace": "external-resources-poc",
            },
        },
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        validate_k8s_object=False,
    )


@fixture
def current(resource: OpenshiftResource) -> OpenshiftResource:
    return resource


@fixture
def desired(resource: OpenshiftResource) -> OpenshiftResource:
    return copy.deepcopy(resource)


def test_update_at_doesnot_triggers_update(
    current: OpenshiftResource,
    desired: OpenshiftResource,
) -> None:
    desired.annotations[SECRET_UPDATED_AT] = datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert SecretHelper.compare(current, desired) is True


def test_new_data_triggers_update(
    current: OpenshiftResource,
    desired: OpenshiftResource,
) -> None:
    desired.annotations[SECRET_UPDATED_AT] = datetime.now(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    desired.body["data"]["new_key"] = "new_value"
    assert SecretHelper.compare(current, desired) is False


def test_current_no_annotation_triggers_update(
    current: OpenshiftResource,
    desired: OpenshiftResource,
) -> None:
    current.annotations.pop(SECRET_UPDATED_AT, None)
    assert SecretHelper.compare(current, desired) is False


def test_current_new_data_dont_triggers_update(
    current: OpenshiftResource,
    desired: OpenshiftResource,
) -> None:
    current.body["data"]["new_key"] = "new_value"
    assert SecretHelper.compare(current, desired) is True


def test_vault_secrets_reconciler_read_secret_preserves_kv_v2_cached_data() -> None:
    """Test that _read_secret doesn't mutate cached data"""
    original_secret_data = {
        "db_host": "example.com",
        "db_password": "secret123",
        SECRET_UPDATED_AT: "2025-11-20T17:24:32Z",
    }
    # Mock secret reader to return the same object (simulating KV v2 cache behavior)
    mock_secrets_reader = create_autospec(SecretReaderBase)
    mock_secrets_reader.read_all.return_value = original_secret_data

    reconciler = VaultSecretsReconciler(
        ri=ResourceInventory(),
        secrets_reader=mock_secrets_reader,
        vault_path="test-path",
        thread_pool_size=1,
        dry_run=True,
    )
    spec = ExternalResourceSpec(
        provision_provider="test-provider",
        provisioner={"name": "test-provisioner"},
        resource={"provider": "test-provider", "identifier": "test-id"},
        namespace={"name": "test-namespace", "cluster": {"name": "test-cluster"}},
    )

    original_secret_data_copy = copy.deepcopy(original_secret_data)
    # Call _read_secret twice (simulating loop iterations accessing same cached object)
    reconciler._read_secret(spec)
    reconciler._read_secret(spec)
    # Confirm original cached data is unchanged
    assert original_secret_data == original_secret_data_copy
