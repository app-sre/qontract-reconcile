import json
import os

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.secret_reader import SecretReader


class SQSGatewayInitError(Exception):
    pass


class SQSGateway:
    """Wrapper around SQS AWS SDK"""

    def __init__(self, accounts, secret_reader: SecretReader):
        queue_url = os.environ.get("gitlab_pr_submitter_queue_url")
        if not queue_url:
            raise SQSGatewayInitError(
                "when /app-interface/app-interface-settings-1.yml#mergeRequestGateway "
                "is set to 'sqs', an ENV variable 'gitlab_pr_submitter_queue_url' needs "
                "to be provided"
            )
        account = self.get_queue_account(accounts, queue_url)
        accounts = [a for a in accounts if a["name"] == account]
        self._aws_api = AWSApi(
            1, accounts, secret_reader=secret_reader, init_users=False
        )
        session = self._aws_api.get_session(account)

        self.sqs = self._aws_api.get_session_client(session, "sqs")
        self.queue_url = queue_url

    def __enter__(self):
        return self

    def __exit__(self, *ext):
        self.cleanup()

    def cleanup(self):
        self._aws_api.cleanup()

    @staticmethod
    def get_queue_account(accounts, queue_url):
        queue_account_uid = queue_url.split("/")[3]
        queue_account_name = [
            a["name"] for a in accounts if a["uid"] == queue_account_uid
        ]
        if len(queue_account_name) != 1:
            raise SQSGatewayInitError(f"account uid not found: {queue_account_uid}")
        return queue_account_name[0]

    def send_message(self, body):
        self.sqs.send_message(QueueUrl=self.queue_url, MessageBody=json.dumps(body))

    def receive_messages(
        self,
        visibility_timeout=30,
        wait_time_seconds=20,
    ):
        messages = self.sqs.receive_message(
            QueueUrl=self.queue_url,
            VisibilityTimeout=visibility_timeout,
            WaitTimeSeconds=wait_time_seconds,
        ).get("Messages", [])
        return [(m["ReceiptHandle"], json.loads(m["Body"])) for m in messages]

    def delete_message(self, receipt_handle):
        self.sqs.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)
