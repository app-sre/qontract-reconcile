from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel

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
from reconcile.typed_queries.external_resources import get_settings
from reconcile.utils import gql
from reconcile.utils.aws_api_typed.api import AWSApi, AWSStaticCredentials
from reconcile.utils.datetime_util import utc_now
from reconcile.utils.differ import diff_mappings
from reconcile.utils.secret_reader import create_secret_reader
from reconcile.utils.state import init_state

TAGS_KEY = "tags.json"

if TYPE_CHECKING:
    from collections.abc import Iterable

    from mypy_boto3_logs.type_defs import LogGroupTypeDef

    from reconcile.utils.aws_api_typed.logs import AWSApiLogs
    from reconcile.utils.gql import GqlApi


QONTRACT_INTEGRATION = "aws_cloudwatch_log_retention"
MANAGED_BY_INTEGRATION_KEY = "managed_by_integration"
MANAGED_TAG = {MANAGED_BY_INTEGRATION_KEY: QONTRACT_INTEGRATION}
DEFAULT_RETENTION_IN_DAYS = 90


class AWSCloudwatchCleanupOption(BaseModel):
    regex: re.Pattern
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


def _is_managed_by_other_integration(tags: dict[str, str]) -> bool:
    managed_by_integration = tags.get(MANAGED_BY_INTEGRATION_KEY)
    return (
        managed_by_integration is not None
        and managed_by_integration != QONTRACT_INTEGRATION
    )


def _reconcile_log_group(
    dry_run: bool,
    log_group: LogGroupTypeDef,
    desired_cleanup_options: Iterable[AWSCloudwatchCleanupOption],
    desired_tags: dict[str, str],
    last_tags: dict[str, str],
    aws_api_logs: AWSApiLogs,
) -> None:
    current_retention_in_days = log_group.get("retentionInDays")
    log_group_name = log_group["logGroupName"]
    log_group_arn = log_group["arn"]

    desired_cleanup_option = _find_desired_cleanup_option(
        log_group_name, desired_cleanup_options
    )

    if (
        desired_cleanup_option.delete_empty_log_group
        and is_empty(log_group)
        and is_longer_than_retention(
            log_group, desired_cleanup_option.retention_in_days
        )
    ):
        tags = aws_api_logs.get_tags(log_group_arn)
        if not _is_managed_by_other_integration(tags):
            logging.info(
                "Deleting empty log group %s",
                log_group_arn,
            )
            if not dry_run:
                aws_api_logs.delete_log_group(log_group_name)
        return

    if (
        current_retention_in_days == desired_cleanup_option.retention_in_days
        and last_tags == desired_tags
    ):
        return

    current_tags = aws_api_logs.get_tags(log_group_arn)
    if _is_managed_by_other_integration(current_tags):
        return

    diff_result = diff_mappings(
        current=current_tags,
        desired=desired_tags,
    )
    if to_delete := diff_result.delete.keys() & last_tags.keys():
        logging.info(
            "Deleting tags %s for log group %s",
            to_delete,
            log_group_arn,
        )
        if not dry_run:
            aws_api_logs.delete_tags(
                log_group_arn,
                to_delete,
            )
    if diff_result.add or diff_result.change:
        logging.info(
            "Setting tags %s for log group %s",
            desired_tags,
            log_group_arn,
        )
        if not dry_run:
            aws_api_logs.set_tags(log_group_arn, desired_tags)

    if current_retention_in_days != desired_cleanup_option.retention_in_days:
        logging.info(
            "Setting %s retention days to %d",
            log_group_arn,
            desired_cleanup_option.retention_in_days,
        )
        if not dry_run:
            aws_api_logs.put_retention_policy(
                log_group_name,
                desired_cleanup_option.retention_in_days,
            )


def _find_desired_cleanup_option(
    log_group_name: str,
    desired_cleanup_options: Iterable[AWSCloudwatchCleanupOption],
) -> AWSCloudwatchCleanupOption:
    """
    Find the first cleanup option that regex matches the log group name.
    If no match is found, return the default cleanup option.

    Args:
        log_group_name: The name of the log group.
        desired_cleanup_options: A list of desired cleanup options.
    Returns:
        The matching cleanup option or the default one.
    """
    for option in desired_cleanup_options:
        if option.regex.match(log_group_name):
            return option
    return DEFAULT_AWS_CLOUDWATCH_CLEANUP_OPTION


def _reconcile_log_groups(
    dry_run: bool,
    aws_account: AWSAccountV1,
    last_tags: dict[str, str],
    default_tags: dict[str, str],
    automation_token: dict[str, str],
) -> dict[str, str]:
    desired_tags = (
        default_tags | get_aws_account_tags(aws_account.organization) | MANAGED_TAG
    )
    for (
        region,
        desired_cleanup_options,
    ) in get_desired_cleanup_options_by_region(aws_account).items():
        aws_credentials = AWSStaticCredentials(
            access_key_id=automation_token["aws_access_key_id"],
            secret_access_key=automation_token["aws_secret_access_key"],
            region=region,
        )
        with AWSApi(aws_credentials) as aws_api:
            aws_api_logs = aws_api.logs
            try:
                for log_group in aws_api_logs.get_log_groups():
                    _reconcile_log_group(
                        dry_run=dry_run,
                        log_group=log_group,
                        desired_cleanup_options=desired_cleanup_options,
                        desired_tags=desired_tags,
                        last_tags=last_tags,
                        aws_api_logs=aws_api_logs,
                    )
            except aws_api_logs.client.exceptions.ClientError as e:
                logging.error(
                    "Error reconciling log groups for %s: %s",
                    aws_account.name,
                    e,
                )
                return last_tags
    return desired_tags


def get_active_aws_accounts(gql_api: GqlApi) -> list[AWSAccountV1]:
    return [
        account
        for account in get_aws_accounts(gql_api)
        if not (
            account.disable
            and account.disable.integrations
            and "aws-cloudwatch-log-retention" in account.disable.integrations
        )
    ]


def get_default_tags(gql_api: GqlApi) -> dict[str, str]:
    try:
        return get_settings(gql_api.query).default_tags
    except ValueError:
        # no settings found
        return {}


def run(dry_run: bool) -> None:
    gql_api = gql.get_api()
    aws_accounts = get_active_aws_accounts(gql_api)
    vault_settings = get_app_interface_vault_settings(query_func=gql_api.query)
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    default_tags = get_default_tags(gql_api)

    with init_state(
        integration=QONTRACT_INTEGRATION,
        secret_reader=secret_reader,
    ) as state:
        last_tags = state.get(TAGS_KEY, {})
        desired_tags = {
            aws_account.name: _reconcile_log_groups(
                dry_run=dry_run,
                aws_account=aws_account,
                last_tags=last_tags.get(aws_account.name, {}),
                default_tags=default_tags,
                automation_token=secret_reader.read_all_secret(
                    aws_account.automation_token
                ),
            )
            for aws_account in aws_accounts
        }
        if not dry_run and desired_tags != last_tags:
            state.add(TAGS_KEY, desired_tags, force=True)
