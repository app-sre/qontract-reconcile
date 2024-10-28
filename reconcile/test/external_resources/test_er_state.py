from collections.abc import Mapping
from typing import Any

from pytest import fixture

from reconcile.external_resources.state import (
    DynamoDBStateAdapter,
    ExternalResourceState,
)


@fixture
def dynamodb_serialized_values() -> dict[str, Any]:
    return {
        DynamoDBStateAdapter.ER_KEY_HASH: {"S": "c9795cf754e47cc31400c7e4bd56486f"},
        DynamoDBStateAdapter.TIMESTAMP: {"S": "2024-01-01T17:14:00"},
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
