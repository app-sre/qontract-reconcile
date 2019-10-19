import utils.gql as gql

from reconcile.queries import AWS_ACCOUNTS_QUERY
from utils.aws_api import AWSApi


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


def run(dry_run=False, thread_pool_size=10, enable_deletion=False):
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
    for k in keys_to_delete:
        print(k['account'])
        print(k['key'])
