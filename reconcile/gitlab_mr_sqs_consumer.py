"""
SQS Consumer to create Gitlab merge requests.
"""

import json
import logging

import reconcile.queries as queries

from utils import mr
from utils.defer import defer
from utils.sqs_gateway import SQSGateway
from utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'gitlab-mr-sqs-consumer'


@defer
def run(dry_run, gitlab_project_id, defer=None):
    settings = queries.get_app_interface_settings()

    accounts = queries.get_aws_accounts()
    sqs_cli = SQSGateway(accounts, settings=settings)

    instance = queries.get_gitlab_instance()
    saas_files = queries.get_saas_files_minimal()
    gitlab_cli = GitLabApi(instance, project_id=gitlab_project_id,
                           settings=settings, saas_files=saas_files)

    while True:
        messages = sqs_cli.receive_messages()
        logging.info('received %s messages', len(messages))

        if not messages:
            break

        for message in messages:
            receipt_handle, body = message[0], message[1]

            logging.info('received message %s with body %s',
                         receipt_handle[:6], json.dumps(body))

            if not dry_run:
                defer(lambda: sqs_cli.delete_message(str(receipt_handle)))
                merge_request = mr.init_from_sqs_message(body)
                merge_request.submit_to_gitlab(gitlab_cli=gitlab_cli)
