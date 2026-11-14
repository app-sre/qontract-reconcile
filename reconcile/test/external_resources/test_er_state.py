from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

from pytest import fixture
from qontract_utils.aws_api_typed.api import AWSApi

from reconcile.external_resources.state import (
    DynamoDBStateAdapter,
    ExternalResourcesStateDynamoDB,
    ExternalResourceState,
    ResourceStatus,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from reconcile.external_resources.model import ExternalResourceKey


def test_single_resource_state_reads_without_scanning(
    key: ExternalResourceKey, dynamodb_serialized_values: Mapping
) -> None:
    api = Mock(spec=AWSApi)
    client = api.dynamodb.boto3_client
    client.get_item.return_value = {"Item": dynamodb_serialized_values}
    state = ExternalResourcesStateDynamoDB(
        api, "test-state", load_partial_resources=False
    )

    assert state.get_external_resource_state(key).key == key
    client.get_item.assert_called_once_with(
        TableName="test-state",
        ConsistentRead=True,
        Key={DynamoDBStateAdapter.ER_KEY_HASH: {"S": key.state_path}},
    )
    client.get_paginator.assert_not_called()


def test_single_resource_status_update_does_not_scan(key: ExternalResourceKey) -> None:
    api = Mock(spec=AWSApi)
    state = ExternalResourcesStateDynamoDB(
        api, "test-state", load_partial_resources=False
    )
    state.update_resource_status(key, ResourceStatus.RECONCILIATION_REQUESTED)

    api.dynamodb.boto3_client.update_item.assert_called_once_with(
        TableName="test-state",
        Key={DynamoDBStateAdapter.ER_KEY_HASH: {"S": key.state_path}},
        UpdateExpression="set resource_status=:new_value",
        ExpressionAttributeValues={":new_value": {"S": "RECONCILIATION_REQUESTED"}},
        ReturnValues="UPDATED_NEW",
    )
    api.dynamodb.boto3_client.get_paginator.assert_not_called()


def test_state_inventory_is_still_loaded_by_default(
    key: ExternalResourceKey, dynamodb_serialized_values: Mapping
) -> None:
    api = Mock(spec=AWSApi)
    paginator = api.dynamodb.boto3_client.get_paginator.return_value
    paginator.paginate.return_value = [{"Items": [dynamodb_serialized_values]}]

    state = ExternalResourcesStateDynamoDB(api, "test-state")

    assert state.get_all_resource_keys() == {key}
    api.dynamodb.boto3_client.get_paginator.assert_called_once_with("scan")


@fixture
def dynamodb_serialized_values() -> dict[str, Any]:
    return {
        DynamoDBStateAdapter.ER_KEY_HASH: {
            "S": "aws/app-sre/aws-iam-role/test-iam-role"
        },  # state_path
        DynamoDBStateAdapter.TIMESTAMP: {"S": "2024-01-01T17:14:00.000000Z"},
        DynamoDBStateAdapter.RESOURCE_STATUS: {"S": "NOT_EXISTS"},
        DynamoDBStateAdapter.ER_KEY: {
            "M": {
                DynamoDBStateAdapter.ER_KEY_PROVISION_PROVIDER: {"S": "aws"},
                DynamoDBStateAdapter.ER_KEY_PROVISIONER_NAME: {"S": "app-sre"},
                DynamoDBStateAdapter.ER_KEY_PROVIDER: {"S": "aws-iam-role"},
                DynamoDBStateAdapter.ER_KEY_IDENTIFIER: {"S": "test-iam-role"},
            }
        },
        DynamoDBStateAdapter.RECONC: {
            "M": {
                DynamoDBStateAdapter.RECONC_INPUT: {"S": "INPUT"},
                DynamoDBStateAdapter.RECONC_ACTION: {"S": "Apply"},
                DynamoDBStateAdapter.RECONC_RESOURCE_HASH: {"S": "0000111100001111"},
                DynamoDBStateAdapter.MODCONF: {
                    "M": {
                        DynamoDBStateAdapter.MODCONF_IMAGE: {"S": "test-image"},
                        DynamoDBStateAdapter.MODCONF_VERSION: {"S": "0.0.1"},
                        DynamoDBStateAdapter.MODCONF_DRIFT_MINS: {"N": "120"},
                        DynamoDBStateAdapter.MODCONF_TIMEOUT_MINS: {"N": "30"},
                        DynamoDBStateAdapter.MODCONF_RESOURCES: {
                            "M": {
                                DynamoDBStateAdapter.MODCONF_RESOURCES_REQUESTS: {
                                    "M": {
                                        DynamoDBStateAdapter.MODCONF_RESOURCES_REQUESTS_CPU: {
                                            "S": "100m"
                                        },
                                        DynamoDBStateAdapter.MODCONF_RESOURCES_REQUESTS_MEMORY: {
                                            "S": "128Mi"
                                        },
                                    }
                                },
                                DynamoDBStateAdapter.MODCONF_RESOURCES_LIMITS: {
                                    "M": {
                                        DynamoDBStateAdapter.MODCONF_RESOURCES_REQUESTS_CPU: {
                                            "S": "None",
                                        },
                                        DynamoDBStateAdapter.MODCONF_RESOURCES_LIMITS_MEMORY: {
                                            "S": "4Gi"
                                        },
                                    }
                                },
                            },
                        },
                    }
                },
            }
        },
    }


def test_dynamodb_serialize(
    state: ExternalResourceState, dynamodb_serialized_values: Mapping
) -> None:
    """Test the serialization method.

    :param state: state fixture populated in conftest.py
    :param dynamodb_serialized_values: expected result
    """
    adapter = DynamoDBStateAdapter()
    result = adapter.serialize(state)
    assert result == dynamodb_serialized_values


def test_dynamodb_deserialize(
    state: ExternalResourceState, dynamodb_serialized_values: Mapping
) -> None:
    # the output_secret_image/version are not stored in the state
    adapter = DynamoDBStateAdapter()
    result = adapter.deserialize(dynamodb_serialized_values)
    # not all fields are stored in the state, therefore we need to compare them separately
    assert result.key == state.key
    assert result.ts == state.ts
    assert result.resource_status == state.resource_status
    assert result.reconciliation.action == state.reconciliation.action
    assert result.reconciliation.input == state.reconciliation.input
    assert result.reconciliation.resource_hash == state.reconciliation.resource_hash
    assert (
        result.reconciliation.module_configuration.image
        == state.reconciliation.module_configuration.image
    )
    assert (
        result.reconciliation.module_configuration.version
        == state.reconciliation.module_configuration.version
    )
    assert (
        result.reconciliation.module_configuration.reconcile_drift_interval_minutes
        == state.reconciliation.module_configuration.reconcile_drift_interval_minutes
    )
    assert (
        result.reconciliation.module_configuration.reconcile_timeout_minutes
        == state.reconciliation.module_configuration.reconcile_timeout_minutes
    )
    # the rest of the fields are not stored in the state
