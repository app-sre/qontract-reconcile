import json
import os
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import (
    Any,
    Optional,
)

from botocore.errorfactory import ClientError
from jinja2 import Template
from mypy_boto3_s3 import S3Client

from reconcile.gql_definitions.common.app_interface_state_settings import (
    AppInterfaceStateConfigurationS3V1,
)
from reconcile.typed_queries.app_interface_state_settings import (
    get_app_interface_state_settings,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
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

    # if state settings are present via env variables, use them
    state_bucket_name = os.environ.get("APP_INTERFACE_STATE_BUCKET")
    state_bucket_account_name = os.environ.get("APP_INTERFACE_STATE_BUCKET_ACCOUNT")
    if state_bucket_name and state_bucket_account_name:
        query = Template(STATE_ACCOUNT_QUERY).render(name=state_bucket_account_name)
        aws_accounts = gql.get_api().query(query)["accounts"]
        return _init_state_from_accounts(
            integration=integration,
            secret_reader=secret_reader,
            bucket_name=state_bucket_name,
            account_name=state_bucket_account_name,
            accounts=aws_accounts,
        )

    # ... otherwise have a look if state settings are present in app-interface-settings-1.yml
    state_settings = get_app_interface_state_settings()
    if not state_settings:
        raise StateInaccessibleException(
            "app-interface state must be configured in order to use stateful integrations. "
            "use one of the following options to provide state config: "
            "* env vars APP_INTERFACE_STATE_BUCKET and APP_INTERFACE_STATE_BUCKET_ACCOUNT "
            "* state settings in app-interface-settings-1.yml"
        )

    if isinstance(state_settings, AppInterfaceStateConfigurationS3V1):
        return _init_state_from_settings(
            integration=integration,
            secret_reader=secret_reader,
            state_settings=state_settings,
        )

    raise StateInaccessibleException(
        f"app-interface-settings-1.yml state provider {state_settings.provider} is not supported."
    )


def _init_state_from_settings(
    integration: str,
    secret_reader: SecretReaderBase,
    state_settings: AppInterfaceStateConfigurationS3V1,
) -> "State":
    """
    Initializes a state object from the app-interface settings.

    :raises StateInaccessibleException: if the bucket is missing
    or not accessible
    """
    return _init_state_from_accounts(
        integration=integration,
        secret_reader=secret_reader,
        bucket_name=state_settings.bucket,
        account_name="settings-account",
        accounts=[
            {
                "name": "settings-account",
                "resourcesDefaultRegion": state_settings.region,
                "automationToken": state_settings.credentials.dict(by_alias=True),
            }
        ],
    )


def _init_state_from_accounts(
    integration: str,
    secret_reader: SecretReaderBase,
    bucket_name: str,
    account_name: str,
    accounts: Iterable[Mapping[str, Any]],
) -> "State":
    aws_account = next(
        (a for a in accounts if a["name"] == account_name),
        None,
    )
    if not aws_account:
        raise StateInaccessibleException(
            f"Can initialize state. app-interface does not define an AWS account named {account_name}"
        )

    aws_api = AWSApi(
        1,
        [aws_account],
        settings=None,
        secret_reader=secret_reader,
        init_users=False,
    )
    session = aws_api.get_session(account_name)
    return State(
        integration=integration,
        bucket=bucket_name,
        client=aws_api.get_session_client(session, "s3"),
    )


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
