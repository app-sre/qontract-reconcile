import logging
import re
import typing
from collections import defaultdict
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


DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION = AWSCloudwatchCleanupOption(
    regex=re.compile(".*"),
    retention_in_days=DEFAULT_RETENTION_IN_DAYS,
    delete_empty_log_group=False,
)


def get_desired_cleanup_options_by_region(
    account: dict,
) -> dict[str, list[AWSCloudwatchCleanupOption]]:
    default_region = account["resourcesDefaultRegion"]
    result = defaultdict(list)
    if cleanup := account.get("cleanup"):
        for cleanup_option in cleanup:
            if cleanup_option["provider"] == "cloudwatch":
                region = cleanup_option.get("region") or default_region
                result[region].append(
                    AWSCloudwatchCleanupOption(
                        regex=re.compile(cleanup_option["regex"]),
                        retention_in_days=cleanup_option["retention_in_days"],
                        delete_empty_log_group=bool(
                            cleanup_option["delete_empty_log_group"]
                        ),
                    )
                )
    if not result:
        result[default_region].append(DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION)
    return result


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
    account_name: str,
    region: str,
    aws_api: AWSApi,
) -> TagStatus:
    tags = aws_api.get_cloudwatch_log_group_tags(
        account_name,
        log_group["arn"],
        region,
    )
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
    account_name: str,
    region: str,
    awsapi: AWSApi,
) -> None:
    current_retention_in_days = aws_log_group.get("retentionInDays")
    log_group_name = aws_log_group["logGroupName"]
    log_group_arn = aws_log_group["arn"]

    desired_cleanup_option = _find_desired_cleanup_option(
        log_group_name, desired_cleanup_options
    )

    if (
        desired_cleanup_option.delete_empty_log_group
        and is_empty(aws_log_group)
        and is_longer_than_retention(
            aws_log_group, desired_cleanup_option.retention_in_days
        )
    ):
        if (
            get_tag_status(aws_log_group, account_name, region, awsapi)
            != TagStatus.MANAGED_BY_OTHER_INTEGRATION
        ):
            logging.info(
                "Deleting empty log group %s",
                log_group_arn,
            )
            if not dry_run:
                awsapi.delete_cloudwatch_log_group(account_name, log_group_name, region)
        return

    if current_retention_in_days == desired_cleanup_option.retention_in_days:
        return

    match get_tag_status(aws_log_group, account_name, region, awsapi):
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
                awsapi.create_cloudwatch_tag(
                    account_name, log_group_arn, MANAGED_TAG, region
                )

    logging.info(
        "Setting %s retention days to %d",
        log_group_arn,
        desired_cleanup_option.retention_in_days,
    )
    if not dry_run:
        awsapi.set_cloudwatch_log_retention(
            account_name,
            log_group_name,
            desired_cleanup_option.retention_in_days,
            region,
        )


def _find_desired_cleanup_option(
    log_group_name: str,
    desired_cleanup_options: Iterable[AWSCloudwatchCleanupOption],
) -> AWSCloudwatchCleanupOption:
    """
    Find the first cleanup option that regex matches the log group name.
    If no match is found, return the default cleanup option.

    :param log_group_name: The name of the log group
    :param desired_cleanup_options: The desired cleanup options
    :return: The desired cleanup option
    """
    return next(
        (o for o in desired_cleanup_options if o.regex.match(log_group_name)),
        DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION,
    )


def _reconcile_log_groups(
    dry_run: bool,
    aws_account: dict,
    awsapi: AWSApi,
) -> None:
    account_name = aws_account["name"]
    desired_cleanup_options_by_region = get_desired_cleanup_options_by_region(
        aws_account
    )
    try:
        for (
            region,
            desired_cleanup_options,
        ) in desired_cleanup_options_by_region.items():
            for aws_log_group in awsapi.get_cloudwatch_log_groups(
                account_name,
                region,
            ):
                _reconcile_log_group(
                    dry_run=dry_run,
                    aws_log_group=aws_log_group,
                    desired_cleanup_options=desired_cleanup_options,
                    account_name=account_name,
                    region=region,
                    awsapi=awsapi,
                )
    except ClientError as e:
        if e.response["Error"]["Code"] == "AccessDeniedException":
            logging.info(
                "Access denied for aws account %s. Skipping...",
                account_name,
            )
        else:
            logging.error(
                "Error reconciling log groups for %s: %s",
                account_name,
                e,
            )


def get_active_aws_accounts() -> list[dict]:
    return [
        a
        for a in get_aws_accounts(cleanup=True)
        if "aws-cloudwatch-log-retention"
        not in (a.get("disable") or {}).get("integrations", [])
    ]


def run(dry_run: bool, thread_pool_size: int) -> None:
    aws_accounts = get_active_aws_accounts()
    with create_awsapi_client(aws_accounts, thread_pool_size) as awsapi:
        for aws_account in aws_accounts:
            _reconcile_log_groups(dry_run, aws_account, awsapi)
