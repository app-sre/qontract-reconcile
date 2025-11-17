from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_logs.type_defs import LogGroupTypeDef


class AWSApiLogs:
    def __init__(self, client: CloudWatchLogsClient) -> None:
        self.client = client

    def get_log_groups(self) -> Iterator[LogGroupTypeDef]:
        paginator = self.client.get_paginator("describe_log_groups")
        for page in paginator.paginate():
            yield from page["logGroups"]

    def delete_log_group(self, log_group_name: str) -> None:
        self.client.delete_log_group(logGroupName=log_group_name)

    def put_retention_policy(
        self,
        log_group_name: str,
        retention_in_days: int,
    ) -> None:
        self.client.put_retention_policy(
            logGroupName=log_group_name,
            retentionInDays=retention_in_days,
        )

    def get_tags(self, arn: str) -> dict[str, str]:
        tags = self.client.list_tags_for_resource(
            resourceArn=self._normalize_log_group_arn(arn),
        )
        return tags.get("tags") or {}

    def set_tags(
        self,
        arn: str,
        tags: dict[str, str],
    ) -> None:
        self.client.tag_resource(
            resourceArn=self._normalize_log_group_arn(arn),
            tags=tags,
        )

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
        return arn.rstrip(":*")
