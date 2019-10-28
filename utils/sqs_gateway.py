import os
import json
import boto3


class SQSGatewayInitError(Exception):
    pass


class SQSGateway(object):
    """Wrapper around SQS AWS SDK"""

    def __init__(self):
        access_key = os.environ['aws_access_key_id']
        secret_key = os.environ['aws_secret_access_key']
        region_name = os.environ['aws_region']
        queue_url = os.environ['gitlab_pr_submitter_queue_url']

        session = boto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name,
        )
        self.sqs = session.client('sqs')
        self.queue_url = queue_url

    def send_message(self, body):
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(body)
        )

    def create_delete_aws_access_key_mr(self, account, path, key):
        body = {
            'pr_type': 'create_delete_aws_access_key_mr',
            'account': account,
            'path': path,
            'key': key
        }
        self.send_message(body)

    def create_delete_user_mr(self, username, paths):
        body = {
            'pr_type': 'create_delete_user_mr',
            'username': username,
            'paths': paths
        }
        self.send_message(body)
