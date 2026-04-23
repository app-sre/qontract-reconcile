from unittest.mock import Mock

import pytest

from reconcile.external_resources.aws import (
    AWSMskConnectFactory,
    AWSMskFactory,
)
from reconcile.external_resources.model import (
    ExternalResource,
    ExternalResourceKey,
    ExternalResourceModuleConfiguration,
    ExternalResourceProvision,
    ExternalResourcesInventory,
    TerraformModuleProvisionData,
)
from reconcile.utils.external_resource_spec import ExternalResourceSpec


@pytest.fixture
def module_conf() -> ExternalResourceModuleConfiguration:
    return ExternalResourceModuleConfiguration(
        image="stable-image",
        version="1.0.0",
        outputs_secret_image="path/to/er-output-secret-image",
        outputs_secret_version="er-output-secret-version",
        reconcile_timeout_minutes=60,
        reconcile_drift_interval_minutes=60,
    )


@pytest.fixture
def msk_cluster_spec() -> ExternalResourceSpec:
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test", "resources_default_region": "us-east-1"},
        resource={
            "identifier": "my-kafka-cluster",
            "provider": "msk",
            "output_resource_name": "creds-msk1",
            "broker_node_group_info": {
                "client_subnets": ["subnet-1", "subnet-2", "subnet-3"],
                "security_groups": ["sg-1"],
                "instance_type": "kafka.t3.small",
                "ebs_volume_size": 100,
            },
            "kafka_version": "3.7.x",
            "number_of_broker_nodes": 3,
        },
        namespace={
            "cluster": {"name": "test_cluster"},
            "name": "test_namespace",
            "environment": {"name": "test_env"},
            "app": {"name": "test_app"},
        },
    )


@pytest.fixture
def msk_connect_spec() -> ExternalResourceSpec:
    return ExternalResourceSpec(
        provision_provider="aws",
        provisioner={"name": "test", "resources_default_region": "us-east-1"},
        resource={
            "identifier": "my-s3-sink",
            "provider": "msk-connect",
            "msk_cluster": "my-kafka-cluster",
            "service_execution_role": "my-connector-role",
            "custom_plugin": {
                "s3_bucket": "my-plugins-bucket",
                "s3_key": "plugins/connector.zip",
                "content_type": "zip",
            },
            "connector_configuration": {
                "topics": "orders",
                "s3.bucket.name": "my-data-lake",
            },
        },
        namespace={
            "cluster": {"name": "test_cluster"},
            "name": "test_namespace",
            "environment": {"name": "test_env"},
            "app": {"name": "test_app"},
        },
    )


@pytest.fixture
def er_inventory(
    msk_cluster_spec: ExternalResourceSpec,
    msk_connect_spec: ExternalResourceSpec,
) -> ExternalResourcesInventory:
    inventory = ExternalResourcesInventory([])
    inventory[ExternalResourceKey.from_spec(msk_cluster_spec)] = msk_cluster_spec
    inventory[ExternalResourceKey.from_spec(msk_connect_spec)] = msk_connect_spec
    return inventory


def _make_provision(identifier: str) -> ExternalResourceProvision:
    return ExternalResourceProvision(
        provision_provider="aws",
        provisioner="test",
        provider="msk-connect",
        identifier=identifier,
        target_cluster="test_cluster",
        target_namespace="test_namespace",
        target_secret_name=f"{identifier}-msk-connect",
        module_provision_data=TerraformModuleProvisionData(
            tf_state_bucket="bucket",
            tf_state_region="us-east-1",
            tf_state_dynamodb_table="table",
            tf_state_key=f"aws/test/msk-connect/{identifier}/terraform.tfstate",
        ),
    )


def test_msk_connect_resolve(
    er_inventory: ExternalResourcesInventory,
    msk_connect_spec: ExternalResourceSpec,
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    secret_reader = Mock()
    secret_reader.read_all.return_value = {
        "bootstrap_brokers_sasl_iam": "b-1.kafka:9098,b-2.kafka:9098",
        "bootstrap_brokers_tls": "b-1.kafka:9094",
    }
    factory = AWSMskConnectFactory(
        er_inventory, secret_reader, "app-sre/integration-outputs/external-resources"
    )

    data = factory.resolve(msk_connect_spec, module_conf)

    # Bootstrap servers resolved from vault secret
    assert data["kafka_cluster_bootstrap_servers"] == "b-1.kafka:9098,b-2.kafka:9098"

    # VPC resolved from MSK cluster defaults
    assert data["vpc"] == {
        "subnets": ["subnet-1", "subnet-2", "subnet-3"],
        "security_groups": ["sg-1"],
    }

    # Service execution role passed through as identifier
    assert data["service_execution_role"] == "my-connector-role"

    # S3 bucket name converted to ARN
    assert data["custom_plugin"]["s3_bucket_arn"] == "arn:aws:s3:::my-plugins-bucket"
    assert "s3_bucket" not in data["custom_plugin"]
    assert data["custom_plugin"]["s3_key"] == "plugins/connector.zip"

    # Connector config passed through
    assert data["connector_configuration"] == {
        "topics": "orders",
        "s3.bucket.name": "my-data-lake",
    }
    assert "msk_cluster" in data

    # Vault secret was read with correct path
    secret_reader.read_all.assert_called_once_with({
        "path": "app-sre/integration-outputs/external-resources/test_cluster/test_namespace/creds-msk1"
    })


def test_msk_connect_resolve_missing_iam_auth(
    er_inventory: ExternalResourcesInventory,
    msk_connect_spec: ExternalResourceSpec,
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    secret_reader = Mock()
    secret_reader.read_all.return_value = {
        "bootstrap_brokers_sasl_iam": "",
        "bootstrap_brokers_sasl_scram": "b-1.kafka:9096",
    }
    factory = AWSMskConnectFactory(
        er_inventory, secret_reader, "app-sre/integration-outputs/external-resources"
    )

    with pytest.raises(ValueError, match="does not have IAM authentication enabled"):
        factory.resolve(msk_connect_spec, module_conf)


def test_msk_connect_validate_empty_connector_configuration(
    er_inventory: ExternalResourcesInventory,
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    secret_reader = Mock()
    factory = AWSMskConnectFactory(er_inventory, secret_reader, "vault/path")
    resource = ExternalResource(
        data={
            "identifier": "my-s3-sink",
            "connector_configuration": {},
            "custom_plugin": {
                "s3_bucket_arn": "arn:aws:s3:::bucket",
                "s3_key": "key",
                "content_type": "zip",
            },
            "kafka_cluster_bootstrap_servers": "b-1:9098",
            "service_execution_role": "role",
        },
        provision=_make_provision("my-s3-sink"),
    )

    with pytest.raises(ValueError, match="connector_configuration must not be empty"):
        factory.validate(resource, module_conf)


def test_msk_connect_validate_valid(
    er_inventory: ExternalResourcesInventory,
    module_conf: ExternalResourceModuleConfiguration,
) -> None:
    secret_reader = Mock()
    factory = AWSMskConnectFactory(er_inventory, secret_reader, "vault/path")
    resource = ExternalResource(
        data={
            "identifier": "my-s3-sink",
            "connector_configuration": {"topics": "orders"},
            "custom_plugin": {
                "s3_bucket_arn": "arn:aws:s3:::bucket",
                "s3_key": "key",
                "content_type": "zip",
            },
            "kafka_cluster_bootstrap_servers": "b-1:9098",
            "service_execution_role": "my-role",
        },
        provision=_make_provision("my-s3-sink"),
    )

    factory.validate(resource, module_conf)


def test_msk_factory_find_linked_msk_connect_resources(
    er_inventory: ExternalResourcesInventory,
    msk_cluster_spec: ExternalResourceSpec,
) -> None:
    secret_reader = Mock()
    factory = AWSMskFactory(er_inventory, secret_reader)

    linked = factory.find_linked_resources(msk_cluster_spec)

    assert linked == {
        ExternalResourceKey(
            provision_provider="aws",
            provisioner_name="test",
            provider="msk-connect",
            identifier="my-s3-sink",
        )
    }
