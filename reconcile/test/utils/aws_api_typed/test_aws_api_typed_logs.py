from unittest.mock import MagicMock, create_autospec

import pytest
from botocore.exceptions import ClientError
from mypy_boto3_logs import CloudWatchLogsClient, DescribeLogGroupsPaginator

from reconcile.utils.aws_api_typed.logs import AWSApiLogs


@pytest.fixture
def mock_logs_client() -> MagicMock:
    mock_client = create_autospec(CloudWatchLogsClient)
    mock_client.exceptions.ClientError = ClientError
    return mock_client


def test_init(mock_logs_client: MagicMock) -> None:
    api = AWSApiLogs(mock_logs_client)
    assert api.client == mock_logs_client


@pytest.fixture
def aws_api_logs(
    mock_logs_client: MagicMock,
) -> AWSApiLogs:
    return AWSApiLogs(mock_logs_client)


def test_get_log_groups(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
) -> None:
    paginator_mock = create_autospec(DescribeLogGroupsPaginator)
    mock_logs_client.get_paginator.return_value = paginator_mock
    expected_log_groups = [
        {
            "logGroupName": "/aws/lambda/function1",
            "creationTime": 1234567890,
            "retentionInDays": 7,
            "metricFilterCount": 0,
            "arn": "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1:*",
            "storedBytes": 1024,
        },
    ]
    paginator_mock.paginate.return_value = [
        {
            "logGroups": expected_log_groups,
        },
    ]

    log_groups = list(aws_api_logs.get_log_groups())

    assert log_groups == expected_log_groups
    mock_logs_client.get_paginator.assert_called_once_with("describe_log_groups")
    paginator_mock.paginate.assert_called_once_with()


def test_delete_log_group(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
) -> None:
    log_group_name = "/aws/lambda/function1"

    aws_api_logs.delete_log_group(log_group_name)

    mock_logs_client.delete_log_group.assert_called_once_with(
        logGroupName=log_group_name,
    )


def test_put_retention_policy(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
) -> None:
    log_group_name = "/aws/lambda/function1"
    retention_in_days = 14

    aws_api_logs.put_retention_policy(log_group_name, retention_in_days)

    mock_logs_client.put_retention_policy.assert_called_once_with(
        logGroupName=log_group_name,
        retentionInDays=retention_in_days,
    )


@pytest.mark.parametrize(
    ("arn", "expected_arn"),
    [
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1:*",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
    ],
)
def test_get_tags(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
    arn: str,
    expected_arn: str,
) -> None:
    expected_tags = {"env": "test"}
    mock_logs_client.list_tags_for_resource.return_value = {"tags": expected_tags}

    tags = aws_api_logs.get_tags(arn)

    assert tags == expected_tags
    mock_logs_client.list_tags_for_resource.assert_called_once_with(
        resourceArn=expected_arn,
    )


@pytest.mark.parametrize(
    ("arn", "expected_arn"),
    [
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1:*",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
    ],
)
def test_set_tags(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
    arn: str,
    expected_arn: str,
) -> None:
    tags = {"env": "test"}

    aws_api_logs.set_tags(arn, tags)

    mock_logs_client.tag_resource.assert_called_once_with(
        resourceArn=expected_arn,
        tags=tags,
    )


@pytest.mark.parametrize(
    ("arn", "expected_arn"),
    [
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
        (
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1:*",
            "arn:aws:logs:us-east-1:123456789012:log-group:/aws/lambda/function1",
        ),
    ],
)
def test_delete_tags(
    aws_api_logs: AWSApiLogs,
    mock_logs_client: MagicMock,
    arn: str,
    expected_arn: str,
) -> None:
    tags = ["env"]

    aws_api_logs.delete_tags(arn, tags)

    mock_logs_client.untag_resource.assert_called_once_with(
        resourceArn=expected_arn,
        tagKeys=tags,
    )
