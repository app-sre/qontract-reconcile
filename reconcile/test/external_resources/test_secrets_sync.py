import copy
from datetime import UTC, datetime
from unittest.mock import Mock

from pytest import fixture

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
    mock_secrets_reader = Mock()
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
    # Call _read_secret twice (simulating loop iterations accessing same cached object)
    reconciler._read_secret(spec)
    reconciler._read_secret(spec)

    # Confirm original cached data is unchanged
    assert SECRET_UPDATED_AT in original_secret_data, (
        "Original cached data was mutated!"
    )
