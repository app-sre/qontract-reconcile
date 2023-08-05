import logging
import re
from collections.abc import Callable
from typing import (
    TYPE_CHECKING,
    Optional,
)

from pydantic import BaseModel

from reconcile import queries
from reconcile.queries import get_aws_accounts
from reconcile.utils.aws_api import AWSApi

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient  # type: ignore
else:
    CloudWatchLogsClient = object

QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_TAG = {"managed_by_integration": QONTRACT_INTEGRATION}


class AWSCloudwatchLogRetention(BaseModel):
    name: str
    acct_uid: str
    log_regex: str
    log_retention_day_length: str


def get_app_interface_cloudwatch_retention_period(aws_acct: dict) -> list:
    results = []
    aws_acct_name = aws_acct.get("name")
    acct_uid = aws_acct.get("uid")
    if aws_acct.get("cleanup"):
        for aws_acct_field in aws_acct.get("cleanup"):  # type: ignore[union-attr]
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


def check_cloudwatch_log_group_tag(
    log_groups: list, client: CloudWatchLogsClient
) -> list:
    log_group_list = []
    for log_group in log_groups:
        log_group_name = log_group.get("logGroupName")
        tag_result = client.list_tags_log_group(logGroupName=log_group_name)
        tag_list = tag_result.get("tags", {})
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
            log_groups = awsapi.get_cloudwatch_logs(aws_acct)
            session = awsapi.get_session(aws_acct["name"])
            region = aws_acct["resourcesDefaultRegion"]
            log_client = awsapi.get_session_client(session, "logs", region)
            log_group_list = check_cloudwatch_log_group_tag(log_groups, log_client)

            for cloudwatch_cleanup_entry in cloudwatch_cleanup_list:
                for log_group in log_group_list:
                    group_name = log_group["logGroupName"]
                    retention_days = log_group.get("retentionInDays")
                    regex_pattern = re.compile(cloudwatch_cleanup_entry.log_regex)
                    if regex_pattern.match(group_name):
                        log_group_tags = log_group["tags"]
                        if not all(
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
                        if retention_days != int(
                            cloudwatch_cleanup_entry.log_retention_day_length
                        ):
                            logging.info(
                                f" Setting {group_name} retention days to {cloudwatch_cleanup_entry.log_retention_day_length}"
                            )
                            if not dry_run:
                                awsapi.set_cloudwatch_log_retention(
                                    aws_acct,
                                    group_name,
                                    int(
                                        cloudwatch_cleanup_entry.log_retention_day_length
                                    ),
                                )
