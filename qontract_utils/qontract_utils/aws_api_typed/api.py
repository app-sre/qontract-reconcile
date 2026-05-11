from __future__ import annotations

import textwrap
from abc import ABC, abstractmethod
from functools import cached_property
from typing import TYPE_CHECKING, Self

from boto3 import Session
from botocore.config import Config
from pydantic import BaseModel

from qontract_utils.aws_api_typed.account import AWSApiAccount
from qontract_utils.aws_api_typed.cloudformation import AWSApiCloudFormation
from qontract_utils.aws_api_typed.dynamodb import AWSApiDynamoDB
from qontract_utils.aws_api_typed.iam import AWSApiIam
from qontract_utils.aws_api_typed.logs import AWSApiLogs
from qontract_utils.aws_api_typed.organization import AWSApiOrganizations
from qontract_utils.aws_api_typed.s3 import AWSApiS3
from qontract_utils.aws_api_typed.service_quotas import AWSApiServiceQuotas
from qontract_utils.aws_api_typed.sts import AWSApiSts
from qontract_utils.aws_api_typed.support import AWSApiSupport

if TYPE_CHECKING:
    from botocore.client import BaseClient

DEFAULT_CONFIG = Config(
    retries={
        "mode": "standard",
        "total_max_attempts": 10,
    },
)


class AWSCredentials(ABC):
    @abstractmethod
    def as_env_vars(self) -> dict[str, str]:
        """Returns a dictionary of environment variables that can be used to authenticate with AWS."""
        ...

    @abstractmethod
    def as_credentials_file(self, profile_name: str = "default") -> str:
        """Returns a string that can be used to write an AWS credentials file."""
        ...

    @abstractmethod
    def build_session(self) -> Session:
        """Builds an AWS session using these credentials."""
        ...


class AWSStaticCredentials(BaseModel, AWSCredentials):
    """A model representing AWS credentials."""

    access_key_id: str
    secret_access_key: str
    region: str

    def as_env_vars(self) -> dict[str, str]:
        return {
            "AWS_ACCESS_KEY_ID": self.access_key_id,
            "AWS_SECRET_ACCESS_KEY": self.secret_access_key,
            "AWS_REGION": self.region,
        }

    def as_credentials_file(self, profile_name: str = "default") -> str:
        return textwrap.dedent(
            f"""\
            [{profile_name}]
            aws_access_key_id = {self.access_key_id}
            aws_secret_access_key = {self.secret_access_key}
            region = {self.region}
            """
        )

    def build_session(self) -> Session:
        return Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
        )


class AWSTemporaryCredentials(AWSStaticCredentials):
    """A model representing temporary AWS credentials."""

    session_token: str

    def as_env_vars(self) -> dict[str, str]:
        env_vars = super().as_env_vars()
        env_vars["AWS_SESSION_TOKEN"] = self.session_token
        return env_vars

    def as_credentials_file(self, profile_name: str = "default") -> str:
        return textwrap.dedent(
            f"""\
            [{profile_name}]
            aws_access_key_id = {self.access_key_id}
            aws_secret_access_key = {self.secret_access_key}
            aws_session_token = {self.session_token}
            region = {self.region}
            """
        )

    def build_session(self) -> Session:
        return Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            aws_session_token=self.session_token,
            region_name=self.region,
        )


class AWSApi:
    """High-level API for AWS services.

    This class provides a high-level API for AWS services like

    * IAM
    * Organizations
    * Service Quotas
    * STS
    * Support

    It also provides a way to assume roles and create temporary sessions.

    Example:

    with AWSApi(AWSStaticCredentials(...)) as api:
        with api.assume_role(... role="MyRole") as role_api:
            role_api.iam.create_user(...)


    This new fully-tested and fully-typed API will replace the old one in the near future.
    Feel free to implement missing methods and AWS servcies as needed.
    """

    def __init__(self, aws_credentials: AWSCredentials) -> None:
        self.session = aws_credentials.build_session()
        self._session_clients: list[BaseClient] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        """Close all clients created by this API instance."""
        for client in self._session_clients:
            client.close()
        self._session_clients = []

    @cached_property
    def account(self) -> AWSApiAccount:
        """Return an AWS Account Api client."""
        client = self.session.client("account", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiAccount(client)

    @cached_property
    def cloudformation(self) -> AWSApiCloudFormation:
        """Return an AWS CloudFormation Api client."""
        client = self.session.client("cloudformation", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiCloudFormation(client)

    @cached_property
    def dynamodb(self) -> AWSApiDynamoDB:
        """Return an AWS DynamoDB Api client."""
        client = self.session.client("dynamodb", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiDynamoDB(client)

    @cached_property
    def iam(self) -> AWSApiIam:
        """Return an AWS IAM Api client."""
        client = self.session.client("iam", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiIam(client)

    @cached_property
    def logs(self) -> AWSApiLogs:
        """Return an AWS Logs Api client."""
        client = self.session.client("logs", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiLogs(client)

    @cached_property
    def organizations(self) -> AWSApiOrganizations:
        """Return an AWS Organizations Api client."""
        client = self.session.client("organizations", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiOrganizations(client)

    @cached_property
    def s3(self) -> AWSApiS3:
        """Return an AWS S3 Api client."""
        client = self.session.client("s3", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiS3(client)

    @cached_property
    def service_quotas(self) -> AWSApiServiceQuotas:
        """Return an AWS Service Quotas Api client."""
        client = self.session.client("service-quotas", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiServiceQuotas(client)

    @cached_property
    def sts(self) -> AWSApiSts:
        """Return an AWS STS Api client."""
        client = self.session.client("sts", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiSts(client)

    @cached_property
    def support(self) -> AWSApiSupport:
        """Return an AWS Support Api client."""
        client = self.session.client("support", config=DEFAULT_CONFIG)
        self._session_clients.append(client)
        return AWSApiSupport(client)

    def assume_role(self, account_id: str, role: str) -> AWSApi:
        """Return a new AWSApi with the assumed role."""
        credentials = self.sts.assume_role(account_id=account_id, role=role)
        return AWSApi(
            AWSTemporaryCredentials(
                access_key_id=credentials.access_key_id,
                secret_access_key=credentials.secret_access_key,
                session_token=credentials.session_token,
                region=self.session.region_name,
            )
        )

    def temporary_session(self, duration_seconds: int = 900) -> AWSApi:
        """Return a new AWSAPI with temporary AWS credentials from a session.

        This is similar to assuming a role, in the sense that the credentials will expire after a certain amount of time.

        These temporary credentials have the same permissions as the session they were built from, except:
        - they can't be used for anything IAM related
        - for the STS API only the AssumeRole and GetSessionToken actions are allowed
        """
        tmp_creds = self.sts.get_session_token(duration_seconds=duration_seconds)
        return AWSApi(
            AWSTemporaryCredentials(
                access_key_id=tmp_creds.access_key_id,
                secret_access_key=tmp_creds.secret_access_key,
                session_token=tmp_creds.session_token,
                region=self.session.region_name,
            )
        )
