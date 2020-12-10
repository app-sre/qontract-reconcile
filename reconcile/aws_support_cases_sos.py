import logging

import reconcile.queries as queries

from reconcile import mr_client_gateway
from reconcile.utils.mr import CreateDeleteAwsAccessKey
from reconcile.utils.aws_api import AWSApi


QONTRACT_INTEGRATION = 'aws-support-cases-sos'


def get_deleted_keys(accounts):
    return {account['name']: account['deleteKeys']
            for account in accounts
            if account['deleteKeys'] not in (None, [])}


def get_keys_to_delete(aws_support_cases):
    search_pattern = 'We have become aware that the AWS Access Key '
    keys = []
    # ref:
    # https://boto3.amazonaws.com/v1/documentation/api/latest/
    # reference/services/support.html#Support.Client.describe_cases
    for account, cases in aws_support_cases.items():
        for case in cases:
            comms = case['recentCommunications']['communications']
            for comm in comms:
                body = comm['body']
                split = body.split(search_pattern, 1)
                if len(split) == 2:  # sentence is found, get the key
                    key = split[1].split(' ')[0]
                    keys.append({'account': account, 'key': key})
    return keys


def act(dry_run, gitlab_project_id, accounts, keys_to_delete):
    if not dry_run and keys_to_delete:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)

    for k in keys_to_delete:
        account = k['account']
        key = k['key']
        logging.info(['delete_aws_access_key', account, key])
        if not dry_run:
            path = 'data' + \
                [a['path'] for a in accounts if a['name'] == account][0]

            mr = CreateDeleteAwsAccessKey(account, path, key)
            mr.submit(cli=mr_cli)


def run(dry_run, gitlab_project_id=None, thread_pool_size=10,
        enable_deletion=False):
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    deleted_keys = get_deleted_keys(accounts)
    existing_keys = aws.get_users_keys()
    aws_support_cases = aws.get_support_cases()
    keys_to_delete_from_cases = get_keys_to_delete(aws_support_cases)
    keys_to_delete = [ktd for ktd in keys_to_delete_from_cases
                      if deleted_keys.get(ktd['account']) is not None
                      and existing_keys.get(ktd['account']) is not None
                      and ktd['key'] not in deleted_keys[ktd['account']]
                      and ktd['key'] in existing_keys[ktd['account']]]
    act(dry_run, gitlab_project_id, accounts, keys_to_delete)
