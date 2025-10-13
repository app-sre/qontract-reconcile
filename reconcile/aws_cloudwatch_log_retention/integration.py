from __future__ import annotations

import logging
import re
import typing
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from botocore.exceptions import ClientError
from pydantic import BaseModel

from reconcile import queries
from reconcile.gql_definitions.aws_cloudwatch_log_retention.aws_accounts import (
    AWSAccountCleanupOptionCloudWatchV1,
    AWSAccountV1,
)
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.typed_queries.aws_account_tags import get_aws_account_tags
from reconcile.typed_queries.aws_cloudwatch_log_retention.aws_accounts import (
    get_aws_accounts,
)
from reconcile.utils import gql
from reconcile.utils.aws_api import AWSApi
from reconcile.utils.datetime_util import utc_now
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.state import init_state

TAGS_KEY = "tags.json"

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mypy_boto3_logs.type_defs import LogGroupTypeDef


QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_BY_INTEGRATION_KEY = "managed_by_integration"
MANAGED_TAG = {MANAGED_BY_INTEGRATION_KEY: QONTRACT_INTEGRATION}
DEFAULT_RETENTION_IN_DAYS = 90


class AWSCloudwatchCleanupOption(BaseModel):
    regex: typing.Pattern
    retention_in_days: int
    delete_empty_log_group: bool


DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION = AWSCloudwatchCleanupOption(
    regex=re.compile(r".*"),
    retention_in_days=DEFAULT_RETENTION_IN_DAYS,
    delete_empty_log_group=False,
)


def get_desired_cleanup_options_by_region(
    account: AWSAccountV1,
) -> dict[str, list[AWSCloudwatchCleanupOption]]:
    default_region = account.resources_default_region
    result = defaultdict(list)
    for cleanup_option in account.cleanup or []:
        if isinstance(cleanup_option, AWSAccountCleanupOptionCloudWatchV1):
            region = cleanup_option.region or default_region
            result[region].append(
                AWSCloudwatchCleanupOption(
                    regex=re.compile(cleanup_option.regex),
                    retention_in_days=cleanup_option.retention_in_days,
                    delete_empty_log_group=bool(cleanup_option.delete_empty_log_group),
                )
            )
    if not result:
        result[default_region].append(DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION)
    return result


def create_awsapi_client(accounts: list[AWSAccountV1], thread_pool_size: int) -> AWSApi:
    settings = queries.get_secret_reader_settings()
    return AWSApi(
        thread_pool_size,
        [account.dict(by_alias=True) for account in accounts],
        settings=settings,
        init_users=False,
    )


def is_empty(log_group: LogGroupTypeDef) -> bool:
    return log_group["storedBytes"] == 0


def is_longer_than_retention(
    log_group: LogGroupTypeDef,
    desired_retention_days: int,
) -> bool:
    return (
        datetime.fromtimestamp(log_group["creationTime"] / 1000, tz=UTC)
        + timedelta(days=desired_retention_days)
        < utc_now()
    )


def get_tags(
    log_group: LogGroupTypeDef,
    account_name: str,
    region: str,
    aws_api: AWSApi,
) -> dict[str, str]:
    return aws_api.get_cloudwatch_log_group_tags(
        account_name,
        log_group["arn"],
        region,
    )


def _is_managed_by_other_integration(tags: dict[str, str]) -> bool:
    managed_by_integration = tags.get(MANAGED_BY_INTEGRATION_KEY)
    return (
        managed_by_integration is not None
        and managed_by_integration != QONTRACT_INTEGRATION
    )


def _reconcile_log_group(
    dry_run: bool,
    aws_log_group: LogGroupTypeDef,
    desired_cleanup_options: Iterable[AWSCloudwatchCleanupOption],
    desired_tags: dict[str, str],
    desired_tags_changed: bool,
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
        tags = get_tags(aws_log_group, account_name, region, awsapi)
        if not _is_managed_by_other_integration(tags):
            logging.info(
                "Deleting empty log group %s",
                log_group_arn,
            )
            if not dry_run:
                awsapi.delete_cloudwatch_log_group(account_name, log_group_name, region)
        return

    if (
        current_retention_in_days == desired_cleanup_option.retention_in_days
        and not desired_tags_changed
    ):
        return

    tags = get_tags(aws_log_group, account_name, region, awsapi)
    if _is_managed_by_other_integration(tags):
        return

    if tags != desired_tags:
        logging.info(
            "Setting tag %s for log group %s",
            desired_tags,
            log_group_arn,
        )
        if not dry_run:
            awsapi.create_cloudwatch_tag(
                account_name, log_group_arn, desired_tags, region
            )

    if current_retention_in_days != desired_cleanup_option.retention_in_days:
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
    aws_account: AWSAccountV1,
    awsapi: AWSApi,
    last_tags: dict[str, str],
) -> dict[str, str]:
    account_name = aws_account.name
    desired_cleanup_options_by_region = get_desired_cleanup_options_by_region(
        aws_account
    )
    desired_tags = get_aws_account_tags(aws_account.organization) | MANAGED_TAG
    desired_tags_changed = desired_tags != last_tags
    for (
        region,
        desired_cleanup_options,
    ) in desired_cleanup_options_by_region.items():
        try:
            for aws_log_group in awsapi.get_cloudwatch_log_groups(
                account_name,
                region,
            ):
                _reconcile_log_group(
                    dry_run=dry_run,
                    aws_log_group=aws_log_group,
                    desired_cleanup_options=desired_cleanup_options,
                    desired_tags=desired_tags,
                    desired_tags_changed=desired_tags_changed,
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
    return desired_tags


def get_active_aws_accounts() -> list[AWSAccountV1]:
    return [
        account
        for account in get_aws_accounts(gql.get_api())
        if not (
            account.disable
            and account.disable.integrations
            and "aws-cloudwatch-log-retention" in account.disable.integrations
        )
    ]


def run(dry_run: bool, thread_pool_size: int) -> None:
    aws_accounts = get_active_aws_accounts()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    with (
        init_state(
            integration=QONTRACT_INTEGRATION, secret_reader=secret_reader
        ) as state,
        create_awsapi_client(aws_accounts, thread_pool_size) as awsapi,
    ):
        last_tags = state.get(TAGS_KEY, {})
        desired_tags = {
            aws_account.name: _reconcile_log_groups(
                dry_run=dry_run,
                aws_account=aws_account,
                last_tags=last_tags.get(aws_account.name, {}),
                awsapi=awsapi,
            )
            for aws_account in aws_accounts
        }
        if not dry_run and desired_tags != last_tags:
            state.add(TAGS_KEY, desired_tags, force=True)
