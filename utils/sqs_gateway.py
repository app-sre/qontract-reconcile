import os
import json

from utils.aws_api import AWSApi


class SQSGatewayInitError(Exception):
    pass


class SQSGateway(object):
    """Wrapper around SQS AWS SDK"""

    def __init__(self, accounts, settings=None):
        queue_url = os.environ['gitlab_pr_submitter_queue_url']
        account = self.get_queue_account(accounts, queue_url)
        aws_api = AWSApi(1, accounts, settings=settings)
        session = aws_api.get_session(account)

        self.sqs = session.client('sqs')
        self.queue_url = queue_url

    @staticmethod
    def get_queue_account(accounts, queue_url):
        queue_account_uid = queue_url.split('/')[3]
        queue_account_name = [a['name'] for a in accounts
                              if a['uid'] == queue_account_uid]
        if len(queue_account_name) != 1:
            raise SQSGatewayInitError(
                'account uid not found: {}'.format(queue_account_uid))
        return queue_account_name[0]

    def send_message(self, body):
        self.sqs.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(body)
        )

    def receive_messages(self, visibility_timeout=30):
        messages = self.sqs.receive_message(
            QueueUrl=self.queue_url,
            VisibilityTimeout=visibility_timeout
        ).get('Messages', [])
        return [(m['ReceiptHandle'], json.loads(m['Body']))
                for m in messages]

    def delete_message(self, receipt_handle):
        self.sqs.delete_message(
            QueueUrl=self.queue_url,
            ReceiptHandle=receipt_handle
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

    def create_app_interface_reporter_mr(self, reports):
        body = {
            'pr_type': 'create_app_interface_reporter_mr',
            'reports': reports
        }
        self.send_message(body)

    def create_update_cluster_version_mr(self, cluster_name, path, version):
        body = {
            'pr_type': 'create_update_cluster_version_mr',
            'cluster_name': cluster_name,
            'path': path,
            'version': version
        }
        self.send_message(body)

    def create_app_interface_notificator_mr(self, notification):
        body = {
            'pr_type': 'create_app_interface_notificator_mr',
            'notification': notification
        }
        self.send_message(body)

    def create_app_interface_notificator_slack_mr(self, notification):
        body = {
            'pr_type': 'create_app_interface_notificator_slack_mr',
            'notification': notification
        }
        self.send_message(body)