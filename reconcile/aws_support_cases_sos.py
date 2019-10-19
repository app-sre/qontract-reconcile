import logging

import utils.gql as gql

from reconcile.queries import AWS_ACCOUNTS_QUERY
from reconcile.queries import GITLAB_INSTANCES_QUERY
from utils.aws_api import AWSApi
from utils.gitlab_api import GitLabApi


def get_deleted_keys(accounts):
    return {account['name']: account['deleteKeys']
            for account in accounts
            if account['deleteKeys'] not in (None, [])}


def get_keys_to_delete(aws_support_cases):
    search_pattern = 'We have become aware that the AWS Access Key '
    keys = []
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


def run(gitlab_project_id, dry_run=False, thread_pool_size=10, enable_deletion=False):
    gqlapi = gql.get_api()
    accounts = gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']
    aws = AWSApi(thread_pool_size, accounts)
    deleted_keys = get_deleted_keys(accounts)
    existing_keys = aws.get_users_keys()
    aws_support_cases = aws.get_support_cases()
    keys_to_delete_from_cases = get_keys_to_delete(aws_support_cases)
    keys_to_delete = [ktd for ktd in keys_to_delete_from_cases
                      if ktd['key'] not in deleted_keys[ktd['account']]
                      and ktd['key'] in existing_keys[ktd['account']]]

    if not dry_run and keys_to_delete:
        # assuming a single GitLab instance for now
        instance = gqlapi.query(GITLAB_INSTANCES_QUERY)['instances'][0]
        gl = GitLabApi(instance, project_id=gitlab_project_id)

    for k in keys_to_delete:
        logging.info(['delete_aws_access_key', k['account'], k['key']])
        if not dry_run:
            path = 'data' + \
                [a['path'] for a in accounts if a['name'] == k['account']][0]
            gl.create_delete_aws_access_key_mr(account, path, k['key'])
