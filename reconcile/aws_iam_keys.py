import utils.gql as gql

from reconcile.queries import AWS_ACCOUNTS_QUERY
from utils.aws_api import AWSApi


def get_keys_to_delete(accounts):
    return {account['name']: account['deleteKeys']
            for account in accounts
            if account['deleteKeys'] not in (None, [])}


def run(dry_run=False, thread_pool_size=10, enable_deletion=False):
    gqlapi = gql.get_api()
    accounts = gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']
    aws = AWSApi(thread_pool_size, accounts)
    keys_to_delete = get_keys_to_delete(accounts)
    aws.delete_keys(dry_run, keys_to_delete)
