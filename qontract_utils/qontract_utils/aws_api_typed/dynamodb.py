from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS
from qontract_utils.hooks import Hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_dynamodb import DynamoDBClient


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiDynamoDB:
    _hooks: Hooks

    def __init__(self, client: DynamoDBClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @property
    def boto3_client(self) -> DynamoDBClient:
        """Gets the RAW boto3 DynamoDB client"""
        return self.client
