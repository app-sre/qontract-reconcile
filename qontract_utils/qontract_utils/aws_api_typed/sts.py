from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from mypy_boto3_sts import STSClient


class AWSCredentials(BaseModel):
    access_key_id: str = Field(..., alias="AccessKeyId")
    secret_access_key: str = Field(..., alias="SecretAccessKey")
    session_token: str = Field(..., alias="SessionToken")
    expiration: datetime = Field(..., alias="Expiration")


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiSts:
    _hooks: Hooks

    def __init__(self, client: STSClient, hooks: Hooks | None = None) -> None:  # noqa: ARG002
        self.client = client

    @invoke_with_hooks(lambda: AWSApiCallContext(method="assume_role", service="sts"))
    def assume_role(self, account_id: str, role: str) -> AWSCredentials:
        """Assume a role and return temporary credentials."""
        assumed_role_object = self.client.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{role}",
            RoleSessionName=role,
        )
        return AWSCredentials(**assumed_role_object["Credentials"])

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_session_token", service="sts")
    )
    def get_session_token(self, duration_seconds: int = 900) -> AWSCredentials:
        """Return temporary credentials."""
        assumed_role_object = self.client.get_session_token(
            DurationSeconds=duration_seconds
        )
        return AWSCredentials(**assumed_role_object["Credentials"])
