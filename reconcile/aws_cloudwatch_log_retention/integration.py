import logging
import re
import typing
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError
from pydantic import BaseModel

from reconcile import queries
from reconcile.queries import get_aws_accounts
from reconcile.utils.aws_api import AWSApi

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient  # type: ignore
else:
    CloudWatchLogsClient = object

QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_BY_INTEGRATION_KEY = "managed_by_integration"
MANAGED_TAG = {MANAGED_BY_INTEGRATION_KEY: QONTRACT_INTEGRATION}
DEFAULT_RETENTION_IN_DAYS = 90


class AWSCloudwatchLogRetention(BaseModel):
    regex: typing.Pattern
    retention_in_days: int


def get_app_interface_cloudwatch_retention_period(
    aws_acct: dict,
) -> list[AWSCloudwatchLogRetention]:
    if cleanup := aws_acct.get("cleanup"):
        return [
            AWSCloudwatchLogRetention(
                regex=re.compile(cleanup_option["regex"]),
                retention_in_days=cleanup_option["retention_in_days"],
            )
            for cleanup_option in cleanup
            if cleanup_option["provider"] == "cloudwatch"
        ]
    return []


def check_cloudwatch_log_group_tag(
    log_groups: list, client: CloudWatchLogsClient
) -> list:
    log_group_list = []
    for log_group in log_groups:
        log_group_name = log_group.get("logGroupName")
        tag_result = client.list_tags_log_group(logGroupName=log_group_name)
        tag_list = tag_result.get("tags", {})
        tag_match = any(
            k == MANAGED_BY_INTEGRATION_KEY and v != QONTRACT_INTEGRATION
            for k, v in tag_list.items()
        )
        if not tag_match:
            log_group_tag_info = {**log_group, "tags": tag_list}
            log_group_list.append(log_group_tag_info)
    return log_group_list


def create_awsapi_client(accounts: list, thread_pool_size: int) -> AWSApi:
    settings = queries.get_secret_reader_settings()
    return AWSApi(thread_pool_size, accounts, settings=settings, init_users=False)


def get_log_group_list(awsapi: AWSApi, aws_acct: dict) -> list:
    log_groups = awsapi.get_cloudwatch_logs(aws_acct)
    session = awsapi.get_session(aws_acct["name"])
    region = aws_acct["resourcesDefaultRegion"]
    log_client = awsapi.get_session_client(session, "logs", region)
    log_group_list = check_cloudwatch_log_group_tag(log_groups, log_client)
    return log_group_list


def run(dry_run: bool, thread_pool_size: int) -> None:
    aws_accounts = get_aws_accounts(cleanup=True)
    with create_awsapi_client(aws_accounts, thread_pool_size) as awsapi:
        for aws_account in aws_accounts:
            aws_account_name = aws_account["name"]
            cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period(
                aws_account
            )
            try:
                aws_log_group_list = get_log_group_list(awsapi, aws_account)
            except ClientError as e:
                if e.response["Error"]["Code"] == "AccessDeniedException":
                    logging.info(
                        "Access denied for aws account %s. Skipping...",
                        aws_account_name,
                    )
                else:
                    logging.error(
                        "Error getting log groups for %s: %s",
                        aws_account_name,
                        e,
                    )
                continue

            for aws_log_group in aws_log_group_list:
                group_name = aws_log_group["logGroupName"]
                retention_days = aws_log_group.get("retentionInDays")

                log_group_tags = aws_log_group["tags"]
                if (
                    log_group_tags.get(MANAGED_BY_INTEGRATION_KEY)
                    != QONTRACT_INTEGRATION
                ):
                    logging.info(
                        "Setting tag %s for log group %s",
                        MANAGED_TAG,
                        group_name,
                    )
                    if not dry_run:
                        awsapi.create_cloudwatch_tag(
                            aws_account, group_name, MANAGED_TAG
                        )
                desired_retention_days = next(
                    (
                        c.retention_in_days
                        for c in cloudwatch_cleanup_list
                        if c.regex.match(group_name)
                    ),
                    DEFAULT_RETENTION_IN_DAYS,
                )
                if retention_days != desired_retention_days:
                    logging.info(
                        "Setting %s retention days to %d",
                        group_name,
                        desired_retention_days,
                    )
                    if not dry_run:
                        awsapi.set_cloudwatch_log_retention(
                            aws_account, group_name, desired_retention_days
                        )
