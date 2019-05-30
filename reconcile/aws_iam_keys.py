import utils.gql as gql

from utils.aws_api import AWSApi

QUERY = """
{
  accounts: awsaccounts_v1 {
    name
    deleteKeys
  }
}
"""


def fetch_keys_to_delete():
    gqlapi = gql.get_api()
    accounts = gqlapi.query(QUERY)['accounts']

    keys_to_delete = {}
    for account in accounts:
        account_name = account['name']
        keys = account['deleteKeys']
        if keys in (None, []):
            continue
        keys_to_delete[account_name] = []
        for key in keys:
            keys_to_delete[account_name].append(key)
    return keys_to_delete


def run(dry_run=False, thread_pool_size=10, enable_deletion=False):
    aws = AWSApi(thread_pool_size)
    keys_to_delete = fetch_keys_to_delete()
    aws.delete_keys(dry_run, keys_to_delete)
