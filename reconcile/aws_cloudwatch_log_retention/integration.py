import logging
import re
from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel

from reconcile import queries
from reconcile.queries import get_aws_accounts
from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"


class AWSCloudwatchLogRetention(BaseModel):
    name: str
    acct_uid: str
    log_regex: str
    log_retention_day_length: str


def get_app_interface_cloudwatch_retention_period(aws_accounts: list) -> list:
    # aws_accounts = get_aws_accounts(cleanup=True)
    results = []
    for aws_acct in aws_accounts:
        aws_acct_name = aws_acct.get("name")
        acct_uid = aws_acct.get("uid")
        if aws_acct.get("cleanup"):
            for aws_acct_field in aws_acct.get("cleanup"):
                if aws_acct_field["provider"] == "cloudwatch":
                    results.append(
                        AWSCloudwatchLogRetention(
                            name=aws_acct_name,
                            acct_uid=acct_uid,
                            log_regex=aws_acct_field["regex"],
                            log_retention_day_length=aws_acct_field[
                                "retention_in_days"
                            ],
                        )
                    )
    return results


def run(dry_run: bool, thread_pool_size: int, defer: Optional[Callable] = None) -> None:
    aws_accounts = get_aws_accounts(cleanup=True)
    cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period(
        aws_accounts
    )
    for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
        settings = queries.get_secret_reader_settings()
        accounts = queries.get_aws_accounts(uid=cloudwatch_cleanup_entry.acct_uid)
        awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
        log_groups = awsapi.get_cloudwatch_logs(accounts[0])
        regex_pattern = re.compile(cloudwatch_cleanup_entry.log_regex)
        for log_group in log_groups:
            group_name = log_group["logGroupName"]
            retention_days = log_group.get("retentionInDays")
            if retention_days is not None:
                if (
                    regex_pattern.match(group_name)
                    and retention_days
                    != cloudwatch_cleanup_entry.log_retention_day_length
                ):
                    logging.info(
                        f" Setting {group_name} retention days to {cloudwatch_cleanup_entry.log_retention_day_length}"
                    )
                    if not dry_run:
                        awsapi.set_cloudwatch_log_retention(
                            accounts[0],
                            log_groups,
                            cloudwatch_cleanup_entry.log_retention_day_length,
                        )
            else:
                logging.info(
                    f"log group {group_name} retentionInDays not specified, setting retention days to {cloudwatch_cleanup_entry.log_retention_day_length}"
                )
                if not dry_run:
                    awsapi.set_cloudwatch_log_retention(
                        accounts[0],
                        log_groups,
                        cloudwatch_cleanup_entry.log_retention_day_length,
                    )
