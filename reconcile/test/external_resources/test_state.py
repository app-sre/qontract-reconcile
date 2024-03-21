from collections.abc import Mapping

from pytest import fixture

from reconcile.external_resources.state import (
    DynamoDBStateAdapater,
    ExternalResourceState,
)


@fixture
def dynamodb_serialized_values() -> dict[str, dict[str, str]]:
    return {
        "resource_key": {"S": "c9795cf754e47cc31400c7e4bd56486f"},
        "key.provision_provider": {"S": "aws"},
        "key.provisioner_name": {"S": "app-sre"},
        "key.provider": {"S": "aws-iam-role"},
        "key.identifier": {"S": "test-iam-role"},
        "ts": {"S": "2024-01-01T17:14:00"},
        "resource_status": {"S": "NOT_EXISTS"},
        "resource_digest": {"S": "00001111000011111"},
        "reconciliation_errors": {"N": "0"},
        "reconcilitation.resource_digest": {"S": "0000111100001111"},
        "reconciliation.image": {"S": "test-image"},
        "reconciliation.input": {"S": "INPUT"},
        "reconciliation.action": {"S": "Apply"},
    }


def test_dynamodb_serialize(
    state: ExternalResourceState, dynamodb_serialized_values: Mapping
) -> None:
    adapter = DynamoDBStateAdapater()
    result = adapter.serialize(state)
    assert result == dynamodb_serialized_values


def test_dynamodb_deserialize(
    state: ExternalResourceState, dynamodb_serialized_values: Mapping
) -> None:
    adapter = DynamoDBStateAdapater()
    result = adapter.deserialize(dynamodb_serialized_values)
    assert result == state
