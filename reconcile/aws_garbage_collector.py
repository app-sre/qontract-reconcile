import reconcile.queries as queries

from utils.aws_api import AWSApi


def run(dry_run=False, thread_pool_size=10,
        enable_deletion=False, io_dir='throughput/'):
    accounts = queries.get_aws_accounts()
    settings = queries.get_app_interface_settings()
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    if dry_run:
        aws.simulate_deleted_users(io_dir)
    aws.map_resources()
    aws.delete_resources_without_owner(dry_run, enable_deletion)
