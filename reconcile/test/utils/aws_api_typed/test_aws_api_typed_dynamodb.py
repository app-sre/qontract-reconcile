from typing import TYPE_CHECKING

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api_typed.dynamodb import AWSApiDynamoDB

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
else:
    DynamoDBClient = object


@pytest.fixture
def dynamodb_client(mocker: MockerFixture) -> DynamoDBClient:
    return mocker.Mock()


@pytest.fixture
def aws_api_dynamodb(dynamodb_client: DynamoDBClient) -> AWSApiDynamoDB:
    return AWSApiDynamoDB(client=dynamodb_client)


def test_aws_api_typed_dynamodb_boto3_client_returns_client(
    aws_api_dynamodb: AWSApiDynamoDB,
) -> None:
    assert isinstance(aws_api_dynamodb.boto3_client, DynamoDBClient)
