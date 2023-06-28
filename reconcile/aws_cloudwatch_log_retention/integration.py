from collections.abc import Callable
import logging
import re
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


def get_app_interface_cloudwatch_retention_period() -> list:
    aws_accounts = get_aws_accounts(cleanup=True)
    results = []
    for aws_acct in aws_accounts:
        aws_acct_name = aws_acct.get("name")
        acct_uid = aws_acct.get("uid")
        if aws_acct.get("cleanup"):
            for x in aws_acct.get("cleanup"):
                if x["provider"] == "cloudwatch":
                    results.append(
                        AWSCloudwatchLogRetention(
                            name=aws_acct_name,
                            acct_uid=acct_uid,
                            log_regex=x["regex"],
                            log_retention_day_length=x["retention_in_days"],
                        )
                    )
    return results


# def parse_log_retention_date(retention_period: str) -> int:
#     if retention_period[-1] == "d":
#         return int(retention_period[:-1])
#     raise ValueError(
#         "Invalid retention period format. Expected format is <numeric value>d"
#     )


def run(dry_run: bool, thread_pool_size: int, defer: Optional[Callable] = None) -> None:
    cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period()
    logging.debug()
    for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
        settings = queries.get_secret_reader_settings()
        accounts = queries.get_aws_accounts(uid=cloudwatch_cleanup_entry.acct_uid)
        awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
        # transformed_retention_day_length = parse_log_retention_date(
        #     cloudwatch_cleanup_entry.log_retention_day_length
        # )
        log_groups = awsapi.get_cloudwatch_logs(accounts[0])
        regex_pattern = re.compile(cloudwatch_cleanup_entry.log_regex)
        for log_group in log_groups:
            group_name = log_group["logGroupName"]
            retention_days = log_group["retentionInDays"]
            if regex_pattern.match(group_name) and retention_days != cloudwatch_cleanup_entry.log_retention_day_length:
                logging.info(f" Setting {group_name} retention days to {cloudwatch_cleanup_entry.log_retention_day_length}")
                if not dry_run:
                    logging.info("we are in here")
                    awsapi.set_cloudwatch_log_retention(group_name, )
                    # cloudwatch_logs.put_retention_policy(logGroupName=group_name, retentionInDays=retention_days)


        # awsapi.set_cloudwatch_log_retention(
        #     accounts[0],
        #     cloudwatch_cleanup_entry.log_regex,
        #     transformed_retention_day_length,
        # )
