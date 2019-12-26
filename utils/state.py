import os
import json

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
        aws_api = AWSApi(1, accounts, settings=settings)
        session = aws_api.get_session(account)

        self.client = session.client('s3')

    def exists(self, key):
        """checks if a key exists in the state
        
        Arguments:
            key {string} -- key to check
        
        Returns:
            bool -- True if key exists in state, else False
        """
        try:
            self.client.head_object(
                Bucket=self.bucket, Key=f"{self.state_path}/{key}")
            return True
        except ClientError:
            return False

    def add(self, key):
        """adds a key to the state and fails if the key already exists
        
        Arguments:
            key {string} -- key to add
        
        Raises:
            KeyError: key already exists in the state
        """
        if self.exists(key):
            raise KeyError(
                f"[state] key {key} already exists in {self.state_path}")
        self.client.put_object(
            Bucket=self.bucket, Key=f"{self.state_path}/{key}")
