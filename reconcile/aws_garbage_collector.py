import utils.gql as gql

from reconcile.queries import AWS_ACCOUNTS_QUERY
from utils.aws_api import AWSApi


def run(dry_run=False, thread_pool_size=10,
        enable_deletion=False, io_dir='throughput/'):
    gqlapi = gql.get_api()
    accounts = gqlapi.query(AWS_ACCOUNTS_QUERY)['accounts']
    aws = AWSApi(thread_pool_size, accounts)
    if dry_run:
        aws.simulate_deleted_users(io_dir)
    aws.map_resources()
    aws.delete_resources_without_owner(dry_run, enable_deletion)
