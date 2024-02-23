from __future__ import annotations

import textwrap
from abc import ABC, abstractmethod
from functools import cached_property
from typing import Any, TypeVar

from boto3 import Session
from botocore.client import BaseClient
from pydantic import BaseModel

import reconcile.utils.aws_api_typed.iam
import reconcile.utils.aws_api_typed.organization
import reconcile.utils.aws_api_typed.sts
from reconcile.utils.aws_api_typed.iam import AWSApiIam
from reconcile.utils.aws_api_typed.organization import AWSApiOrganizations
from reconcile.utils.aws_api_typed.sts import AWSApiSts

SubApi = TypeVar("SubApi")


class AWSCredentials(ABC):
    @abstractmethod
    def as_env_vars(self) -> dict[str, str]:
        """
        Returns a dictionary of environment variables that can be used to authenticate with AWS.
        """
        ...

    @abstractmethod
    def as_credentials_file(self, profile_name: str = "default") -> str:
        """
        Returns a string that can be used to write an AWS credentials file.
        """
        ...

    @abstractmethod
    def build_session(self) -> Session:
        """
        Builds an AWS session using these credentials.
        """
        ...


class AWSStaticCredentials(BaseModel, AWSCredentials):
    """
    A model representing AWS credentials.
    """

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
    """
    A model representing temporary AWS credentials.
    """

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
    def __init__(self, aws_credentials: AWSCredentials) -> None:
        self.session = aws_credentials.build_session()
        self._session_clients: list[BaseClient] = []

    def __enter__(self) -> AWSApi:
        return self

    def __exit__(self, *exec: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close all clients created by this API instance."""
        for client in self._session_clients:
            client.close()
        self._session_clients = []

    def _init_sub_api(self, api_cls: type[SubApi]) -> SubApi:
        """Return a new or cached sub api client."""
        match api_cls:
            case reconcile.utils.aws_api_typed.iam.AWSApiIam:
                client = self.session.client("iam")
                api = api_cls(client)  # type: ignore # mypy bug, it doesn't recognize that api_cls is callable
            case reconcile.utils.aws_api_typed.organization.AWSApiOrganizations:
                client = self.session.client("organizations")
                api = api_cls(client)
            case reconcile.utils.aws_api_typed.sts.AWSApiSts:
                client = self.session.client("sts")
                api = api_cls(client)
            case _:
                raise ValueError(f"Unknown API class: {api_cls}")

        self._session_clients.append(client)
        return api

    @cached_property
    def sts(self) -> AWSApiSts:
        """Return an AWS STS Api client."""
        return self._init_sub_api(AWSApiSts)

    @cached_property
    def organizations(self) -> AWSApiOrganizations:
        """Return an AWS Organizations Api client."""
        return self._init_sub_api(AWSApiOrganizations)

    @cached_property
    def iam(self) -> AWSApiIam:
        """Return an AWS IAM Api client."""
        return self._init_sub_api(AWSApiIam)

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
