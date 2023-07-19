import logging
import re
from collections.abc import Callable
from typing import Optional

from pydantic import BaseModel

from reconcile import queries
from reconcile.queries import get_aws_accounts
from reconcile.utils.aws_api import AWSApi

QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_TAG = {"Key": "managed_by_integration", "Value": QONTRACT_INTEGRATION}


class AWSCloudwatchLogRetention(BaseModel):
    name: str
    acct_uid: str
    log_regex: str
    log_retention_day_length: str


def get_app_interface_cloudwatch_retention_period(aws_acct: any) -> list:
    results = []
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
                        log_retention_day_length=aws_acct_field["retention_in_days"],
                    )
                )
    return results


def check_cloudwatch_log_group_tag(log_groups: list, cloudwatch_logs: any):
    log_group_list = []
    for log_group in log_groups:
        log_group_name = log_group.get("logGroupName")
        log_group_tags = cloudwatch_logs.list_tags_log_group(
            logGroupName=log_group_name
        )
        tag_list = log_group_tags.get("tags", {})
        tag_match = any(
            k == "managed_by_integration" and (v == "terraform_resources")
            for k, v in tag_list.items()
        )
        if not tag_match:
            log_group_tag_info = {**log_group, "tags": tag_list}
            log_group_list.append(log_group_tag_info)
    return log_group_list


def run(dry_run: bool, thread_pool_size: int, defer: Optional[Callable] = None) -> None:
    aws_accounts = get_aws_accounts(cleanup=True)
    for aws_acct in aws_accounts:
        if aws_acct.get("cleanup"):
            cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period(
                aws_acct
            )
            settings = queries.get_secret_reader_settings()
            accounts = queries.get_aws_accounts(uid=aws_acct.get("uid"))
            awsapi = AWSApi(1, accounts, settings=settings, init_users=False)
            cloudwatch_logs = awsapi._account_cloudwatch_client(aws_acct["name"])

            all_log_groups = awsapi.get_cloudwatch_logs(aws_acct)
            log_groups = check_cloudwatch_log_group_tag(all_log_groups, cloudwatch_logs)
            for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
                for log_group in log_groups:
                    group_name = log_group["logGroupName"]
                    retention_days = log_group.get("retentionInDays")
                    regex_pattern = re.compile(cloudwatch_cleanup_entry.log_regex)
                    if regex_pattern.match(group_name):
                        log_group_tags = log_group["tags"]
                        if all(
                            item in log_group_tags.items()
                            for item in MANAGED_TAG.items()
                        ):
                            logging.info(
                                f"Setting tag {MANAGED_TAG} for group {group_name}"
                            )
                            if not dry_run:
                                awsapi.create_cloudwatch_tag(
                                    aws_acct, group_name, MANAGED_TAG
                                )
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
                                aws_acct,
                                group_name,
                                cloudwatch_cleanup_entry.log_retention_day_length,
                            )
