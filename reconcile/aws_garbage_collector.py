from reconcile import queries
from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws-garbage-collector"


def run(dry_run: bool, thread_pool_size: int = 10) -> None:
    accounts = [a for a in queries.get_aws_accounts() if a.get("garbageCollection")]
    settings = queries.get_app_interface_settings()
    with AWSApi(thread_pool_size, accounts, settings=settings) as aws:
        aws.map_resources()
        aws.delete_resources_without_owner(dry_run)
