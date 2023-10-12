import logging
import re
import typing
from collections.abc import Iterable
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


def get_desired_retentions(
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


def create_awsapi_client(accounts: list, thread_pool_size: int) -> AWSApi:
    settings = queries.get_secret_reader_settings()
    return AWSApi(thread_pool_size, accounts, settings=settings, init_users=False)


def _reconcile_log_group(
    dry_run: bool,
    aws_log_group: dict,
    desired_retentions: Iterable[AWSCloudwatchLogRetention],
    aws_account: dict,
    awsapi: AWSApi,
) -> None:
    current_retention_in_days = aws_log_group.get("retentionInDays")
    log_group_name = aws_log_group["logGroupName"]
    desired_retention_days = next(
        (
            c.retention_in_days
            for c in desired_retentions
            if c.regex.match(log_group_name)
        ),
        DEFAULT_RETENTION_IN_DAYS,
    )
    if current_retention_in_days == desired_retention_days:
        return

    log_group_arn = aws_log_group["arn"]
    log_group_tags = awsapi.get_cloudwatch_log_group_tags(aws_account, log_group_arn)
    if managed_by_integration := log_group_tags.get(MANAGED_BY_INTEGRATION_KEY):
        if managed_by_integration != QONTRACT_INTEGRATION:
            return
    else:
        logging.info(
            "Setting tag %s for log group %s",
            MANAGED_TAG,
            log_group_arn,
        )
        if not dry_run:
            awsapi.create_cloudwatch_tag(aws_account, log_group_arn, MANAGED_TAG)

    logging.info(
        "Setting %s retention days to %d",
        log_group_arn,
        desired_retention_days,
    )
    if not dry_run:
        awsapi.set_cloudwatch_log_retention(
            aws_account, log_group_name, desired_retention_days
        )


def _reconcile_log_groups(
    dry_run: bool,
    aws_account: dict,
    awsapi: AWSApi,
) -> None:
    aws_account_name = aws_account["name"]
    desired_retentions = get_desired_retentions(aws_account)
    try:
        for aws_log_group in awsapi.get_cloudwatch_log_groups(aws_account):
            _reconcile_log_group(
                dry_run=dry_run,
                aws_log_group=aws_log_group,
                desired_retentions=desired_retentions,
                aws_account=aws_account,
                awsapi=awsapi,
            )
    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDeniedException":
            logging.info(
                "Access denied for aws account %s. Skipping...",
                aws_account_name,
            )
        else:
            logging.error(
                "Error reconciling log groups for %s: %s",
                aws_account_name,
                e,
            )


def run(dry_run: bool, thread_pool_size: int) -> None:
    aws_accounts = get_aws_accounts(cleanup=True)
    with create_awsapi_client(aws_accounts, thread_pool_size) as awsapi:
        for aws_account in aws_accounts:
            _reconcile_log_groups(dry_run, aws_account, awsapi)
