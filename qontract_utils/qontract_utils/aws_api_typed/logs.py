from __future__ import annotations

from typing import TYPE_CHECKING

from qontract_utils.aws_api_typed._hooks import AWS_DEFAULT_HOOKS, AWSApiCallContext
from qontract_utils.hooks import Hooks, invoke_with_hooks, with_hooks

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_logs.type_defs import LogGroupTypeDef


@with_hooks(hooks=AWS_DEFAULT_HOOKS)
class AWSApiLogs:
    _hooks: Hooks

    def __init__(
        self,
        client: CloudWatchLogsClient,
        hooks: Hooks | None = None,  # noqa: ARG002
    ) -> None:
        self.client = client

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="get_log_groups", service="logs")
    )
    def get_log_groups(self) -> Iterator[LogGroupTypeDef]:
        paginator = self.client.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            yield from page["logGroups"]

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="delete_log_group", service="logs")
    )
    def delete_log_group(self, log_group_name: str) -> None:
        self.client.delete_log_group(logGroupName=log_group_name)

    @invoke_with_hooks(
        lambda: AWSApiCallContext(method="put_retention_policy", service="logs")
    )
    def put_retention_policy(
        self,
        log_group_name: str,
        retention_in_days: int,
    ) -> None:
        self.client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=retention_in_days,
        )

    @invoke_with_hooks(lambda: AWSApiCallContext(method="get_tags", service="logs"))
    def get_tags(self, arn: str) -> dict[str, str]:
        tags = self.client.list_tags_for_resource(
            resourceArn=self._normalize_log_group_arn(arn),
        )
        return tags.get("tags") or {}

    @invoke_with_hooks(lambda: AWSApiCallContext(method="set_tags", service="logs"))
    def set_tags(
        self,
        arn: str,
        tags: dict[str, str],
    ) -> None:
        self.client.tag_resource(
            resourceArn=self._normalize_log_group_arn(arn),
            tags=tags,
        )

    @invoke_with_hooks(lambda: AWSApiCallContext(method="delete_tags", service="logs"))
    def delete_tags(
        self,
        arn: str,
        tag_keys: Iterable[str],
    ) -> None:
        self.client.untag_resource(
            resourceArn=self._normalize_log_group_arn(arn),
            tagKeys=list(tag_keys),
        )

    @staticmethod
    def _normalize_log_group_arn(arn: str) -> str:
        """
        Normalize a log group ARN by removing any trailing ":*".

        DescribeLogGroups response arn has additional :* at the end.

        Args:
            arn: The ARN of the log group.

        Returns:
            The normalized ARN without the trailing ":*".
        """
        return arn.removesuffix(":*")
