from collections.abc import Generator
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_logs
from pytest_mock import MockerFixture

from reconcile.aws_cloudwatch_log_retention.integration import (
    get_desired_retentions,
    run,
)

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient  # type: ignore
else:
    CloudWatchLogsClient = object
    CreateImageResultTypeDef = dict


@pytest.fixture
def cloudwatchlogs_client() -> Generator[CloudWatchLogsClient, None, None]:
    with mock_logs():
        yield boto3.client("logs", region_name="us-east-1")


@pytest.fixture(autouse=True)
def log_group_tf_tag(cloudwatchlogs_client: CloudWatchLogsClient) -> list:
    log_group_name1 = "some-group"
    tags1 = {"key": "value", "managed_by_integration": "terraform_resources"}

    cloudwatchlogs_client.create_log_group(logGroupName=log_group_name1)
    cloudwatchlogs_client.tag_log_group(logGroupName=log_group_name1, tags=tags1)

    log_group_name2 = "some-group2"
    tags2 = {"key2": "value2"}

    cloudwatchlogs_client.create_log_group(logGroupName=log_group_name2)
    cloudwatchlogs_client.tag_log_group(logGroupName=log_group_name2, tags=tags2)

    describe_log_output = cloudwatchlogs_client.describe_log_groups(
        logGroupNamePattern="some"
    )
    log_output_list = describe_log_output.get("logGroups")

    return log_output_list


@pytest.fixture
def test_cloudwatch_account() -> dict[str, Any]:
    return {
        "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
        "cleanup": [
            {
                "provider": "cloudwatch",
                "regex": "some-path*",
                "retention_in_days": 30,
            },
            {
                "provider": "cloudwatch",
                "regex": "some-other-path*",
                "retention_in_days": 60,
            },
        ],
        "consoleUrl": "https://some-url.com/console",
        "name": "some-account-name",
        "uid": "0123456789",
        "resourcesDefaultRegion": "us-east-1",
    }


def test_get_desired_retentions(
    test_cloudwatch_account: dict,
) -> None:
    refined_cloudwatch_list = get_desired_retentions(test_cloudwatch_account)
    assert len(refined_cloudwatch_list) == 2


def setup_mocks(
    mocker: MockerFixture,
    aws_accounts: list[dict],
    log_groups: list[dict],
    tags: dict[str, Any],
) -> MagicMock:
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.get_aws_accounts",
        return_value=aws_accounts,
    )
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.queries.get_secret_reader_settings",
        return_value={},
    )
    aws_api = mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.AWSApi",
        autospec=True,
    )
    mocked_aws_api = aws_api.return_value.__enter__.return_value
    mocked_aws_api.get_cloudwatch_log_groups.return_value = iter(log_groups)
    mocked_aws_api.get_cloudwatch_log_group_tags.return_value = tags
    return mocked_aws_api


@pytest.fixture
def log_group_with_unset_retention() -> dict[str, Any]:
    return {
        "logGroupName": "group-without-retention",
        "storedBytes": 123,
        "creationTime": 1433189500783,
        "arn": "arn:aws:logs:us-west-2:0123456789012:log-group:group-without-retention:*",
    }


@pytest.fixture
def empty_tags() -> dict[str, str]:
    return {}


@pytest.fixture
def managed_by_aws_cloudwatch_log_retention_tags() -> dict[str, str]:
    return {
        "managed_by_integration": "aws_cloudwatch_log_retention",
    }


@pytest.fixture
def managed_by_terraform_resources_tags() -> dict[str, str]:
    return {
        "managed_by_integration": "terraform_resources",
    }


def test_run_with_unset_retention_log_group_and_default_cleanup(
    mocker: MockerFixture,
    test_cloudwatch_account: dict[str, Any],
    log_group_with_unset_retention: dict[str, Any],
    empty_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention],
        tags=empty_tags,
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_called_once_with(
        test_cloudwatch_account,
        log_group_with_unset_retention["arn"],
    )

    mocked_aws_api.create_cloudwatch_tag.assert_called_once_with(
        test_cloudwatch_account,
        log_group_with_unset_retention["arn"],
        {"managed_by_integration": "aws_cloudwatch_log_retention"},
    )

    mocked_aws_api.set_cloudwatch_log_retention.assert_called_once_with(
        test_cloudwatch_account,
        "group-without-retention",
        90,
    )


@pytest.fixture
def log_group_with_unset_retention_and_matching_name() -> dict[str, Any]:
    return {
        "logGroupName": "some-path-group-without-retention",
        "storedBytes": 123,
        "creationTime": 1433189500783,
        "arn": "arn:aws:logs:us-west-2:0123456789012:log-group:some-path-group-without-retention:*",
    }


def test_run_with_unset_retention_log_group_and_matching_cleanup(
    mocker: MockerFixture,
    test_cloudwatch_account: dict[str, Any],
    log_group_with_unset_retention_and_matching_name: dict[str, Any],
    empty_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention_and_matching_name],
        tags=empty_tags,
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_called_once_with(
        test_cloudwatch_account,
        log_group_with_unset_retention_and_matching_name["arn"],
    )

    mocked_aws_api.create_cloudwatch_tag.assert_called_once_with(
        test_cloudwatch_account,
        log_group_with_unset_retention_and_matching_name["arn"],
        {"managed_by_integration": "aws_cloudwatch_log_retention"},
    )

    mocked_aws_api.set_cloudwatch_log_retention.assert_called_once_with(
        test_cloudwatch_account,
        "some-path-group-without-retention",
        30,
    )


@pytest.fixture
def log_group_with_desired_retention() -> dict[str, Any]:
    return {
        "logGroupName": "group-with-desired-retention",
        "retentionInDays": 90,
        "storedBytes": 123,
        "creationTime": 1433189500783,
        "arn": "arn:aws:logs:us-west-2:0123456789012:log-group:group-with-desired-retention:*",
    }


def test_run_with_matching_retention_log_group(
    mocker: MockerFixture,
    test_cloudwatch_account: dict[str, Any],
    log_group_with_desired_retention: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_desired_retention],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_not_called()
    mocked_aws_api.create_cloudwatch_tag.assert_not_called()
    mocked_aws_api.set_cloudwatch_log_retention.assert_not_called()


def test_run_with_log_group_managed_by_terraform_resources(
    mocker: MockerFixture,
    test_cloudwatch_account: dict[str, Any],
    log_group_with_unset_retention: dict[str, Any],
    managed_by_terraform_resources_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention],
        tags=managed_by_terraform_resources_tags,
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_called_once_with(
        test_cloudwatch_account,
        log_group_with_unset_retention["arn"],
    )
    mocked_aws_api.create_cloudwatch_tag.assert_not_called()
    mocked_aws_api.set_cloudwatch_log_retention.assert_not_called()
