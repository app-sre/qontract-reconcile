"""
SQS Consumer to create Gitlab merge requests.
"""

import json
import logging

import reconcile.queries as queries

from reconcile.utils import mr
from reconcile.utils.sqs_gateway import SQSGateway
from reconcile.utils.gitlab_api import GitLabApi


QONTRACT_INTEGRATION = 'gitlab-mr-sqs-consumer'


def run(dry_run, gitlab_project_id):
    settings = queries.get_app_interface_settings()

    accounts = queries.get_aws_accounts()
    sqs_cli = SQSGateway(accounts, settings=settings)

    instance = queries.get_gitlab_instance()
    saas_files = queries.get_saas_files_minimal(v1=True, v2=True)
    gitlab_cli = GitLabApi(instance, project_id=gitlab_project_id,
                           settings=settings, saas_files=saas_files)

    while True:
        messages = sqs_cli.receive_messages()
        logging.info('received %s messages', len(messages))

        if not messages:
            break

        for message in messages:
            # Let's first delete all the message we received,
            # otherwise they will come back in 30s.
            receipt_handle = message[0]
            sqs_cli.delete_message(str(receipt_handle))

        for message in messages:
            # Time to process the messages. Any failure here is not
            # critical, even though we already deleted the messaged,
            # since the producers will keep re-sending the message
            # until the MR gets merged to app-interface
            receipt_handle, body = message[0], message[1]
            logging.info('received message %s with body %s',
                         receipt_handle[:6], json.dumps(body))

            if not dry_run:
                merge_request = mr.init_from_sqs_message(body)
                merge_request.submit_to_gitlab(gitlab_cli=gitlab_cli)
