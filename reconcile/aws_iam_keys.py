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

    return {account['name']: account['deleteKeys']
            for account in accounts
            if account['deleteKeys'] not in (None, [])}


def run(dry_run=False, thread_pool_size=10, enable_deletion=False):
    aws = AWSApi(thread_pool_size)
    keys_to_delete = fetch_keys_to_delete()
    aws.delete_keys(dry_run, keys_to_delete)
