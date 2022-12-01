"""
SQS Consumer to create Gitlab merge requests.
"""

import json
import logging
import sys

from reconcile import queries
from reconcile.utils import mr
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.sqs_gateway import SQSGateway

QONTRACT_INTEGRATION = "gitlab-mr-sqs-consumer"


def run(dry_run, gitlab_project_id):
    secret_reader = SecretReader(queries.get_secret_reader_settings())

    accounts = queries.get_queue_aws_accounts()
    sqs_cli = SQSGateway(accounts, secret_reader)

    instance = queries.get_gitlab_instance()
    gitlab_cli = GitLabApi(
        instance, project_id=gitlab_project_id, secret_reader=secret_reader
    )

    errors_occured = False
    while True:
        messages = sqs_cli.receive_messages()
        logging.info("received %s messages", len(messages))

        if not messages:
            # sqs_cli.receive_messages delivers messages in chunks
            # until the queue is empty... when that happens,
            # we end this integration run
            break

        # not all integrations are going to resend their MR messages
        # therefore we need to be careful not to delete any messages
        # before they have been properly handled

        for m in messages:
            receipt_handle, body = m[0], m[1]
            logging.info(
                "received message %s with body %s", receipt_handle[:6], json.dumps(body)
            )

            if not dry_run:
                try:
                    merge_request = mr.init_from_sqs_message(body)
                    merge_request.submit_to_gitlab(gitlab_cli=gitlab_cli)
                    sqs_cli.delete_message(str(receipt_handle))
                except mr.UnknownMergeRequestType as ex:
                    # Received an unknown MR type.
                    # This could be a producer being on a newer version
                    # of qontract-reconcile than the consumer.
                    # Therefore we don't delete it from the queue for
                    # potential future processing.
                    # TODO - monitor age of messages in queue
                    logging.warning(ex)
                    errors_occured = True
                except mr.MergeRequestProcessingError as processing_error:
                    logging.error(processing_error)
                    errors_occured = True

    if errors_occured:
        sys.exit(1)
