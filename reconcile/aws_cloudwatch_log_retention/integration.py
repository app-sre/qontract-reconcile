import logging
import re
import typing
from collections.abc import Iterable
from datetime import (
    datetime,
    timedelta,
)
from enum import Enum
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


class AWSCloudwatchCleanupOption(BaseModel):
    regex: typing.Pattern
    retention_in_days: int
    delete_empty_log_group: bool


def default_aws_cloudwatch_cleanup_option() -> AWSCloudwatchCleanupOption:
    return AWSCloudwatchCleanupOption(
        regex=re.compile(".*"),
        retention_in_days=DEFAULT_RETENTION_IN_DAYS,
        delete_empty_log_group=False,
    )


def get_desired_cleanup_options(
    aws_acct: dict,
) -> list[AWSCloudwatchCleanupOption]:
    if cleanup := aws_acct.get("cleanup"):
        return [
            AWSCloudwatchCleanupOption(
                regex=re.compile(cleanup_option["regex"]),
                retention_in_days=cleanup_option["retention_in_days"],
                delete_empty_log_group=bool(cleanup_option["delete_empty_log_group"]),
            )
            for cleanup_option in cleanup
            if cleanup_option["provider"] == "cloudwatch"
        ]
    return []


def create_awsapi_client(accounts: list, thread_pool_size: int) -> AWSApi:
    settings = queries.get_secret_reader_settings()
    return AWSApi(thread_pool_size, accounts, settings=settings, init_users=False)


def is_empty(
    log_group: dict,
) -> bool:
    return log_group["storedBytes"] == 0


def is_longer_than_retention(
    log_group: dict,
    desired_retention_days: int,
) -> bool:
    return (
        datetime.fromtimestamp(log_group["creationTime"] / 1000)
        + timedelta(days=desired_retention_days)
        < datetime.utcnow()
    )


class TagStatus(Enum):
    NOT_SET = "NOT_SET"
    MANAGED_BY_CURRENT_INTEGRATION = "MANAGED_BY_CURRENT_INTEGRATION"
    MANAGED_BY_OTHER_INTEGRATION = "MANAGED_BY_OTHER_INTEGRATION"


def get_tag_status(
    log_group: dict,
    aws_account: dict,
    aws_api: AWSApi,
) -> TagStatus:
    tags = aws_api.get_cloudwatch_log_group_tags(aws_account, log_group["arn"])
    managed_by_integration = tags.get(MANAGED_BY_INTEGRATION_KEY)
    if managed_by_integration is None:
        return TagStatus.NOT_SET
    if managed_by_integration == QONTRACT_INTEGRATION:
        return TagStatus.MANAGED_BY_CURRENT_INTEGRATION
    return TagStatus.MANAGED_BY_OTHER_INTEGRATION


def _reconcile_log_group(
    dry_run: bool,
    aws_log_group: dict,
    desired_cleanup_options: Iterable[AWSCloudwatchCleanupOption],
    aws_account: dict,
    awsapi: AWSApi,
) -> None:
    current_retention_in_days = aws_log_group.get("retentionInDays")
    log_group_name = aws_log_group["logGroupName"]
    log_group_arn = aws_log_group["arn"]

    desired_cleanup_option = next(
        (o for o in desired_cleanup_options if o.regex.match(log_group_name)),
        default_aws_cloudwatch_cleanup_option(),
    )

    if (
        desired_cleanup_option.delete_empty_log_group
        and is_empty(aws_log_group)
        and is_longer_than_retention(
            aws_log_group, desired_cleanup_option.retention_in_days
        )
    ):
        if (
            get_tag_status(aws_log_group, aws_account, awsapi)
            != TagStatus.MANAGED_BY_OTHER_INTEGRATION
        ):
            logging.info(
                "Deleting empty log group %s",
                log_group_arn,
            )
            if not dry_run:
                awsapi.delete_cloudwatch_log_group(aws_account, log_group_name)
        return

    if current_retention_in_days == desired_cleanup_option.retention_in_days:
        return

    match get_tag_status(aws_log_group, aws_account, awsapi):
        case TagStatus.MANAGED_BY_OTHER_INTEGRATION:
            return
        case TagStatus.MANAGED_BY_CURRENT_INTEGRATION:
            pass
        case TagStatus.NOT_SET:
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
        desired_cleanup_option.retention_in_days,
    )
    if not dry_run:
        awsapi.set_cloudwatch_log_retention(
            aws_account, log_group_name, desired_cleanup_option.retention_in_days
        )


def _reconcile_log_groups(
    dry_run: bool,
    aws_account: dict,
    awsapi: AWSApi,
) -> None:
    aws_account_name = aws_account["name"]
    desired_cleanup_options = get_desired_cleanup_options(aws_account)
    try:
        for aws_log_group in awsapi.get_cloudwatch_log_groups(aws_account):
            _reconcile_log_group(
                dry_run=dry_run,
                aws_log_group=aws_log_group,
                desired_cleanup_options=desired_cleanup_options,
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


def get_active_aws_accounts() -> list[dict]:
    return [
        a
        for a in get_aws_accounts(cleanup=True)
        if "aws-cloudwatch-log-retention"
        not in a.get("disable", {}).get("integrations", [])
    ]


def run(dry_run: bool, thread_pool_size: int) -> None:
    aws_accounts = get_active_aws_accounts()
    with create_awsapi_client(aws_accounts, thread_pool_size) as awsapi:
        for aws_account in aws_accounts:
            _reconcile_log_groups(dry_run, aws_account, awsapi)
