import os
import json

from typing import Any, Iterable, Mapping, Optional

from botocore.errorfactory import ClientError

from reconcile.utils.aws_api import AWSApi


class StateInaccessibleException(Exception):
    pass


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

    def __init__(
        self,
        integration: str,
        accounts: Iterable[Mapping[str, Any]],
        settings: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Initiates S3 client from AWSApi."""
        self.state_path = f"state/{integration}" if integration else "state"
        self.bucket = os.environ["APP_INTERFACE_STATE_BUCKET"]
        account = os.environ["APP_INTERFACE_STATE_BUCKET_ACCOUNT"]
        accounts = [a for a in accounts if a["name"] == account]
        aws_api = AWSApi(1, accounts, settings=settings, init_users=False)
        session = aws_api.get_session(account)

        self.client = session.client("s3")

        # check if the bucket exists
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError as details:
            raise StateInaccessibleException(
                f"Bucket {self.bucket} is not accessible - {str(details)}"
            )

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
            else:
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
