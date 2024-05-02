from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient
else:
    DynamoDBClient = object


class AWSApiDynamoDB:
    def __init__(self, client: DynamoDBClient) -> None:
        self.client = client

    @property
    def boto3_client(self) -> DynamoDBClient:
        """Gets the RAW boto3 DynamoDB client"""
        return self.client
