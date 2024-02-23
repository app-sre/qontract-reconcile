from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from mypy_boto3_iam import IAMClient
else:
    IAMClient = object


class AWSAccessKey(BaseModel):
    access_key_id: str = Field(..., alias="AccessKeyId")
    secret_access_key: str = Field(..., alias="SecretAccessKey")


class AWSUser(BaseModel):
    user_name: str = Field(..., alias="UserName")
    user_id: str = Field(..., alias="UserId")
    arn: str = Field(..., alias="Arn")
    path: str = Field(..., alias="Path")


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
        user = self.client.create_user(
            UserName=user_name,
        )
        return AWSUser(**user["User"])

    def attach_user_policy(self, user_name: str, policy_arn: str) -> None:
        """Attach a policy to a user."""
        self.client.attach_user_policy(
            UserName=user_name,
            PolicyArn=policy_arn,
        )

    def create_account_alias(self, account_alias: str) -> None:
        """Create an account alias."""
        self.client.create_account_alias(AccountAlias=account_alias)
