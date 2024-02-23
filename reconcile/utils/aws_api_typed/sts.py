from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_sts import STSClient
else:
    STSClient = object


class AWSCredentials(BaseModel):
    access_key_id: str = Field(..., alias="AccessKeyId")
    secret_access_key: str = Field(..., alias="SecretAccessKey")
    session_token: str = Field(..., alias="SessionToken")
    expiration: datetime = Field(..., alias="Expiration")


class AWSApiSts:
    def __init__(self, client: STSClient) -> None:
        self.client = client

    def assume_role(self, account_id: str, role: str) -> AWSCredentials:
        """Assume a role and return temporary credentials."""
        assumed_role_object = self.client.assume_role(
            RoleArn=f"arn:aws:iam::{account_id}:role/{role}",
            RoleSessionName=role,
        )
        return AWSCredentials(**assumed_role_object["Credentials"])

    def get_session_token(self, duration_seconds: int = 900) -> AWSCredentials:
        """Return temporary credentials."""
        assumed_role_object = self.client.get_session_token(
            DurationSeconds=duration_seconds
        )
        return AWSCredentials(**assumed_role_object["Credentials"])
