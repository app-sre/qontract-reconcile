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
MANAGED_TAG = {"managed_by_integration": QONTRACT_INTEGRATION}


class AWSCloudwatchLogRetention(BaseModel):
    name: str
    acct_uid: str
    log_regex: typing.Pattern
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
                        log_regex=re.compile(aws_acct_field["regex"]),
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
    app_interface_aws_accounts = get_aws_accounts(cleanup=True)
    with create_awsapi_client(app_interface_aws_accounts, thread_pool_size) as awsapi:
        for app_interface_aws_acct in app_interface_aws_accounts:
            aws_act_name = app_interface_aws_acct["name"]
            cloudwatch_cleanup_list = []
            if app_interface_aws_acct.get("cleanup"):
                cloudwatch_cleanup_list = get_app_interface_cloudwatch_retention_period(
                    app_interface_aws_acct
                )
            aws_log_group_list = []
            try:
                aws_log_group_list = get_log_group_list(awsapi, app_interface_aws_acct)
            except ClientError as e:
                if e.response["Error"]["Code"] == "AccessDeniedException":
                    logging.info(
                        f" Access denied for aws account {aws_act_name}. Skipping..."
                    )
                    continue
            for aws_log_group in aws_log_group_list:
                group_name = aws_log_group["logGroupName"]
                retention_days = aws_log_group.get("retentionInDays")

                cloudwatch_cleanup_entry = next(
                    (
                        c
                        for c in cloudwatch_cleanup_list
                        if c.log_regex.match(group_name)
                    ),
                    None,
                )
                log_group_tags = aws_log_group["tags"]
                if log_group_tags.get("managed_by_integration") != QONTRACT_INTEGRATION:
                    logging.info(
                        f"Setting tag {MANAGED_TAG} for log group {group_name}"
                    )
                    if not dry_run:
                        awsapi.create_cloudwatch_tag(
                            app_interface_aws_acct, group_name, MANAGED_TAG
                        )
                desired_retention_days = (
                    90
                    if cloudwatch_cleanup_entry is None
                    else int(cloudwatch_cleanup_entry.log_retention_day_length)
                )
                if retention_days != desired_retention_days:
                    logging.info(
                        f" Setting {group_name} retention days to {desired_retention_days}"
                    )
                    if not dry_run:
                        awsapi.set_cloudwatch_log_retention(
                            app_interface_aws_acct, group_name, desired_retention_days
                        )
