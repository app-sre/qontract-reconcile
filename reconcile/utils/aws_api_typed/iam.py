from __future__ import annotations

from typing import TYPE_CHECKING

import botocore
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_iam import IAMClient


class AWSAccessKey(BaseModel):
    access_key_id: str = Field(..., alias="AccessKeyId")
    secret_access_key: str = Field(..., alias="SecretAccessKey")


class AWSUser(BaseModel):
    user_name: str = Field(..., alias="UserName")
    user_id: str = Field(..., alias="UserId")
    arn: str = Field(..., alias="Arn")
    path: str = Field(..., alias="Path")


class AWSEntityAlreadyExistsError(Exception):
    """Raised when the user already exists in IAM."""


class AWSApiIam:
    def __init__(self, client: IAMClient) -> None:
        self.client = client

    def create_access_key(self, user_name: str) -> AWSAccessKey:
        """Create an access key for a given user."""
        credentials = self.client.create_access_key(
            UserName=user_name,
        )
        return AWSAccessKey(**credentials["AccessKey"])

    def create_user(self, user_name: str) -> AWSUser:
        """Create a new IAM user."""
        try:
            user = self.client.create_user(UserName=user_name)
            return AWSUser(**user["User"])
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                raise AWSEntityAlreadyExistsError(
                    f"User {user_name} already exists"
                ) from e
            raise

    def attach_user_policy(self, user_name: str, policy_arn: str) -> None:
        """Attach a policy to a user."""
        self.client.attach_user_policy(
            UserName=user_name,
            PolicyArn=policy_arn,
        )

    def get_account_alias(self) -> str:
        """Get the account alias."""
        return self.client.list_account_aliases()["AccountAliases"][0]

    def set_account_alias(self, account_alias: str) -> None:
        """Set the account alias."""
        try:
            self.client.create_account_alias(AccountAlias=account_alias)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "EntityAlreadyExists":
                if self.get_account_alias() != account_alias:
                    raise ValueError(
                        "Account alias already exists for another AWS account. Choose another one!"
                    ) from e
            elif e.response["Error"]["Code"] == "AccessDeniedException":
                # AccessDeniedException can occur if the user does not have permission to create an account alias.
                # This can happen if the alias is already set and we don't have permission to change it.
                # If the existing alias is the one we want, we can ignore the error.
                if self.get_account_alias() != account_alias:
                    raise
