from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from mypy_boto3_dynamodb import DynamoDBClient

from reconcile.utils.aws_api_typed.dynamodb import AWSApiDynamoDB

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


@pytest.fixture
def dynamodb_client(mocker: MockerFixture) -> DynamoDBClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_dynamodb(dynamodb_client: DynamoDBClient) -> AWSApiDynamoDB:
    return AWSApiDynamoDB(client=dynamodb_client)


def test_aws_api_typed_dynamodb_boto3_client_returns_client(
    aws_api_dynamodb: AWSApiDynamoDB, dynamodb_client: DynamoDBClient
) -> None:
    assert isinstance(aws_api_dynamodb.boto3_client, type(dynamodb_client))
