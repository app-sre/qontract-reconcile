import os

from botocore.errorfactory import ClientError

from utils.aws_api import AWSApi


class State(object):
    """
    A state object to be used by stateful integrations.
    A stateful integration is one that has to do each action only once,
    and there is no source of truth to validate against.

    Good example: email-sender should only send each email once
    Bad example: openshift-resources' source of truth is the clusters

    :param integration: name of calling integration
    :param accounts: Graphql AWS accounts query results
    :param settings: App Interface settings

    :type integration: string
    :type accounts: list
    :type settings: dict
    """
    def __init__(self, integration, accounts, settings=None):
        """Initiates S3 client from AWSApi."""
        self.state_path = f"state/{integration}"
        self.bucket = os.environ['APP_INTERFACE_STATE_BUCKET']
        account = os.environ['APP_INTERFACE_STATE_BUCKET_ACCOUNT']
        accounts = [a for a in accounts if a['name'] == account]
        aws_api = AWSApi(1, accounts, settings=settings)
        session = aws_api.get_session(account)

        self.client = session.client('s3')

    def exists(self, key):
        """
        Checks if a key exists in the state.

        :param key: key to check

        :type key: string
        """
        try:
            self.client.head_object(
                Bucket=self.bucket, Key=f"{self.state_path}/{key}")
            return True
        except ClientError:
            return False

    def ls(self):
        """
        Returns a list of keys in the state
        """
        objects = self.client.list_objects(
            Bucket=self.bucket, Prefix=self.state_path)['Contents']
        return [o['Key'].replace(self.state_path, '') for o in objects]

    def add(self, key):
        """
        Adds a key to the state and fails if the key already exists

        :param key: key to add

        :type key: string
        """
        if self.exists(key):
            raise KeyError(
                f"[state] key {key} already exists in {self.state_path}")
        self.client.put_object(
            Bucket=self.bucket, Key=f"{self.state_path}/{key}")

    def rm(self, key):
        """
        Removes a key from the state and fails if the key does not exists

        :param key: key to remove

        :type key: string
        """
        if not self.exists(key):
            raise KeyError(
                f"[state] key {key} does not exists in {self.state_path}")
        self.client.delete_object(
            Bucket=self.bucket, Key=f"{self.state_path}/{key}")
