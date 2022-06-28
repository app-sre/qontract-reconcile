from reconcile import queries

from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws-garbage-collector"


def run(dry_run, thread_pool_size=10):
    accounts = [a for a in queries.get_aws_accounts() if a.get("garbageCollection")]
    settings = queries.get_app_interface_settings()
    aws = AWSApi(thread_pool_size, accounts, settings=settings)
    aws.map_resources()
    aws.delete_resources_without_owner(dry_run)
