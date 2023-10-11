import json
import logging
import os
from abc import abstractmethod
from typing import (
    Any,
    Optional,
)

import boto3
from botocore.errorfactory import ClientError
from jinja2 import Template
from mypy_boto3_s3 import S3Client
from pydantic import BaseModel

from reconcile.gql_definitions.common.app_interface_state_settings import (
    AppInterfaceStateConfigurationS3V1,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret
from reconcile.typed_queries.app_interface_state_settings import (
    get_app_interface_state_settings,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import aws_config_file_path
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)


class StateInaccessibleException(Exception):
    pass


STATE_ACCOUNT_QUERY = """
{
  accounts: awsaccounts_v1 (name: "{{ name }}")
  {
    name
    resourcesDefaultRegion
    automationToken {
      path
      field
      version
      format
    }
  }
}
"""


def init_state(
    integration: str,
    secret_reader: Optional[SecretReaderBase] = None,
) -> "State":
    if not secret_reader:
        vault_settings = get_app_interface_vault_settings()
        secret_reader = create_secret_reader(use_vault=vault_settings.vault)

    s3_settings = acquire_state_settings(secret_reader)

    return State(
        integration=integration,
        bucket=s3_settings.bucket,
        client=s3_settings.build_client(),
    )


class S3StateConfiguration(BaseModel):
    bucket: str
    region: str

    @abstractmethod
    def build_client(self) -> S3Client:
        pass


class S3CredsBasedStateConfiguration(S3StateConfiguration):
    access_key_id: str
    secret_access_key: str

    def build_client(self) -> S3Client:
        session = boto3.Session(
            aws_access_key_id=self.access_key_id,
            aws_secret_access_key=self.secret_access_key,
            region_name=self.region,
        )
        return session.client("s3")


class S3ProfileBasedStateConfiguration(S3StateConfiguration):
    profile: str

    def build_client(self) -> S3Client:
        session = boto3.Session(profile_name=self.profile, region_name=self.region)
        return session.client("s3")


def acquire_state_settings(secret_reader: SecretReaderBase) -> S3StateConfiguration:
    """
    Finds the settings for the app-interface state provider in the following order:

    * env variables pointing to a bucket and an AWS profile
    * env variables pointing to static credentials
    * env variables pointing to a bucket and a vault secret for creds
    * env variables pointing to a bucket and ann AWS account from app-interface for creds
    * state settings in app-interface-settings-1.yml

    If no settings can be found, a StateInaccessibleException is raised.
    """
    state_bucket_name = os.environ.get("APP_INTERFACE_STATE_BUCKET")
    state_bucket_region = os.environ.get("APP_INTERFACE_STATE_BUCKET_REGION")
    state_bucket_account_name = os.environ.get("APP_INTERFACE_STATE_BUCKET_ACCOUNT")
    state_bucket_access_key_id = os.environ.get(
        "APP_INTERFACE_STATE_BUCKET_ACCESS_KEY_ID"
    )
    state_bucket_secret_access_key = os.environ.get(
        "APP_INTERFACE_STATE_BUCKET_SECRET_ACCESS_KEY"
    )
    state_bucket_vault_secret = os.environ.get("APP_INTERFACE_STATE_VAULT_SECRET")
    state_bucket_vault_secret_version = os.environ.get(
        "APP_INTERFACE_STATE_VAULT_SECRET_VERSION"
    )

    state_bucket_aws_profile = os.environ.get("APP_INTERFACE_STATE_AWS_PROFILE")

    # if an AWS config file can be found and a profile for state usage is set ...
    if (
        state_bucket_name
        and state_bucket_region
        and aws_config_file_path()
        and state_bucket_aws_profile
    ):
        logging.debug(f"access state via AWS profile {state_bucket_aws_profile}")
        return S3ProfileBasedStateConfiguration(
            bucket=state_bucket_name,
            region=state_bucket_region,
            profile=state_bucket_aws_profile,
        )

    # if the env vars point towards a vault secret that contains the credentials ...
    if state_bucket_name and state_bucket_region and state_bucket_vault_secret:
        logging.debug(
            f"access state via access credentials from vault secret {state_bucket_vault_secret} version {state_bucket_vault_secret_version or 'latest'})"
        )
        secret = secret_reader.read_all_secret(
            VaultSecret(
                path=state_bucket_vault_secret,
                field="all",
                format=None,
                version=int(state_bucket_vault_secret_version)
                if state_bucket_vault_secret_version
                else None,
            )
        )
        return S3CredsBasedStateConfiguration(
            bucket=state_bucket_name,
            region=state_bucket_region,
            access_key_id=secret["aws_access_key_id"],
            secret_access_key=secret["aws_secret_access_key"],
        )

    # if the env vars contain actual AWS credentials, lets use them ...
    if (
        state_bucket_name
        and state_bucket_region
        and state_bucket_access_key_id
        and state_bucket_secret_access_key
    ):
        logging.debug("access state via static credentials from env variables :(")
        return S3CredsBasedStateConfiguration(
            bucket=state_bucket_name,
            region=state_bucket_region,
            access_key_id=state_bucket_access_key_id,
            secret_access_key=state_bucket_secret_access_key,
        )

    # if the env vars point towards an AWS account mentioned in app-interface ...
    if state_bucket_name and state_bucket_account_name:
        logging.debug(
            f"access state via {state_bucket_account_name} automation token from app-interface"
        )
        account = _get_aws_account_by_name(state_bucket_account_name)
        if not account:
            raise StateInaccessibleException(
                f"The AWS account {state_bucket_account_name} that holds the state bucket can't be found in app-interface."
            )
        secret = secret_reader.read_all_secret(
            VaultSecret(**account["automationToken"])
        )
        return S3CredsBasedStateConfiguration(
            bucket=state_bucket_name,
            region=state_bucket_region or account["resourcesDefaultRegion"],
            access_key_id=secret["aws_access_key_id"],
            secret_access_key=secret["aws_secret_access_key"],
        )

    # ... otherwise have a look if state settings are present in app-interface-settings-1.yml
    ai_settings = get_app_interface_state_settings()
    if ai_settings:
        logging.debug("access state via app-interface settings")
        if isinstance(ai_settings, AppInterfaceStateConfigurationS3V1):
            secret = secret_reader.read_all_secret(ai_settings.credentials)
            return S3CredsBasedStateConfiguration(
                bucket=ai_settings.bucket,
                region=ai_settings.region,
                access_key_id=secret["aws_access_key_id"],
                secret_access_key=secret["aws_secret_access_key"],
            )
        raise StateInaccessibleException(
            f"The app-interface state provider {ai_settings.provider} is not supported."
        )

    raise StateInaccessibleException(
        "app-interface state must be configured to use stateful integrations. "
        "use one of the following options to provide state config: "
        "* env vars APP_INTERFACE_STATE_BUCKET, APP_INTERFACE_STATE_BUCKET_REGION, APP_INTERFACE_STATE_AWS_PROFILE and AWS_CONFIG (hosting the requested profile) \n"
        "* env vars APP_INTERFACE_STATE_BUCKET, APP_INTERFACE_STATE_BUCKET_REGION, APP_INTERFACE_STATE_VAULT_SECRET (and optionally APP_INTERFACE_STATE_VAULT_SECRET_VERSION) \n"
        "* env vars APP_INTERFACE_STATE_BUCKET, APP_INTERFACE_STATE_BUCKET_REGION, APP_INTERFACE_STATE_BUCKET_ACCESS_KEY_ID, APP_INTERFACE_STATE_BUCKET_SECRET_ACCESS_KEY \n"
        "* env vars APP_INTERFACE_STATE_BUCKET, APP_INTERFACE_STATE_BUCKET_REGION and APP_INTERFACE_STATE_BUCKET_ACCOUNT if the mentioned AWS account is present in app-interface \n"
        "* state settings in app-interface-settings-1.yml"
    )


def _get_aws_account_by_name(name: str) -> Optional[dict[str, Any]]:
    query = Template(STATE_ACCOUNT_QUERY).render(name=name)
    aws_accounts = gql.get_api().query(query)["accounts"]
    if aws_accounts:
        return aws_accounts[0]
    return None


class State:
    """
    A state object to be used by stateful integrations.
    A stateful integration is one that has to do each action only once,
    and there is no source of truth to validate against.

    Good example: email-sender should only send each email once
    Bad example: openshift-resources' source of truth is the clusters

    :param integration: name of calling integration
    :param accounts: Graphql AWS accounts query results
    :param settings: App Interface settings

    :raises StateInaccessibleException: if the bucket is missing
    or not accessible
    """

    def __init__(self, integration: str, bucket: str, client: S3Client) -> None:
        """Initiates S3 client from AWSApi."""
        self.state_path = f"state/{integration}" if integration else "state"
        self.bucket = bucket
        self.client = client

        # check if the bucket exists
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as details:
            raise StateInaccessibleException(
                f"Bucket {self.bucket} is not accessible - {str(details)}"
            )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cleanup()

    def cleanup(self):
        """
        Closes the S3 client
        """
        self.client.close()

    def exists(self, key):
        """
        Checks if a key exists in the state.

        :param key: key to check

        :type key: string

        :raises StateInaccessibleException: if the bucket is missing or
        permissions are insufficient or a general AWS error occurred
        """
        key_path = f"{self.state_path}/{key}"
        try:
            self.client.head_object(Bucket=self.bucket, Key=key_path)
            return True
        except ClientError as details:
            error_code = details.response.get("Error", {}).get("Code", None)
            if error_code == "404":
                return False

            raise StateInaccessibleException(
                f"Can not access state key {key_path} "
                f"in bucket {self.bucket} - {str(details)}"
            )

    def ls(self):
        """
        Returns a list of keys in the state
        """
        objects = self.client.list_objects_v2(
            Bucket=self.bucket, Prefix=f"{self.state_path}/"
        )

        if "Contents" not in objects:
            return []

        contents = objects["Contents"]

        while objects["IsTruncated"]:
            objects = self.client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=f"{self.state_path}/",
                ContinuationToken=objects["NextContinuationToken"],
            )

            contents += objects["Contents"]

        return [c["Key"].replace(self.state_path, "") for c in contents]

    def add(self, key, value=None, force=False):
        """
        Adds a key/value to the state and fails if the key already exists

        :param key: key to add
        :param value: (optional) value of the state, defaults to None

        :type key: string
        """
        if self.exists(key) and not force:
            raise KeyError(f"[state] key {key} already " f"exists in {self.state_path}")
        self[key] = value

    def rm(self, key):
        """
        Removes a key from the state and fails if the key does not exists

        :param key: key to remove

        :type key: string
        """
        if not self.exists(key):
            raise KeyError(f"[state] key {key} does not exists in {self.state_path}")
        self.client.delete_object(Bucket=self.bucket, Key=f"{self.state_path}/{key}")

    def get(self, key, *args):
        """
        Gets a key value from the state and return the default
        value or raises and exception if the key does not exist.

        "*args" is used to provide the default as the first argument.

        :param key: key to get

        :type key: string
        """
        try:
            return self[key]
        except KeyError:
            if args:
                return args[0]
            raise

    def get_all(self, path):
        """
        Gets all keys and values from the state in the specified path.
        """
        return {
            k.replace(f"{path}/", "").strip("/"): self.get(k.lstrip("/"))
            for k in self.ls()
            if k.startswith(f"/{path}")
        }

    def __getitem__(self, item):
        try:
            response = self.client.get_object(
                Bucket=self.bucket, Key=f"{self.state_path}/{item}"
            )
            return json.loads(response["Body"].read())
        except ClientError as details:
            if details.response["Error"]["Code"] == "NoSuchKey":
                raise KeyError(item)
            raise
        except json.decoder.JSONDecodeError:
            raise KeyError(item)

    def __setitem__(self, key, value):
        self.client.put_object(
            Bucket=self.bucket, Key=f"{self.state_path}/{key}", Body=json.dumps(value)
        )
