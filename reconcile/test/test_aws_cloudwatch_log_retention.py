import string
from collections.abc import Callable, Generator, Iterable
from datetime import UTC, datetime, timedelta
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import MagicMock, create_autospec

import boto3
import pytest
from moto import mock_logs
from pytest_mock import MockerFixture

from reconcile.aws_cloudwatch_log_retention.integration import (
    get_desired_cleanup_options_by_region,
    run,
)
from reconcile.gql_definitions.aws_cloudwatch_log_retention.aws_accounts import (
    AWSAccountV1,
)
from reconcile.utils.gql import GqlApi

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient
    from mypy_boto3_logs.type_defs import LogGroupTypeDef
else:
    LogGroupTypeDef = CloudWatchLogsClient = object


@pytest.fixture
def cloudwatchlogs_client() -> Generator[CloudWatchLogsClient, None, None]:
    with mock_logs():
        yield boto3.client("logs", region_name="us-east-1")


@pytest.fixture(autouse=True)
def log_group_tf_tag(
    cloudwatchlogs_client: CloudWatchLogsClient,
) -> list[LogGroupTypeDef]:
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

    return log_output_list or []


@pytest.fixture
def test_cloudwatch_account(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "path": "/aws/some/path/account.yml",
            "name": "some-account-name",
            "uid": string.digits,
            "terraformUsername": None,
            "consoleUrl": "https://some-url.com/console",
            "resourcesDefaultRegion": "us-east-1",
            "supportedDeploymentRegions": None,
            "providerVersion": "3.14.159",
            "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
            "automationToken": {
                "path": "app-sre/some/path/config",
                "field": "all",
                "version": None,
                "format": None,
            },
            "enableDeletion": None,
            "deletionApprovals": None,
            "disable": None,
            "deleteKeys": None,
            "premiumSupport": True,
            "ecrs": None,
            "partition": None,
            "cleanup": [
                {
                    "provider": "cloudwatch",
                    "regex": "some-path*",
                    "retention_in_days": 30,
                    "delete_empty_log_group": None,
                    "region": None,
                },
                {
                    "provider": "cloudwatch",
                    "regex": "some-other-path*",
                    "retention_in_days": 60,
                    "delete_empty_log_group": True,
                    "region": "us-east-1",
                },
            ],
        },
    )


def test_get_desired_cleanup_options(
    test_cloudwatch_account: AWSAccountV1,
) -> None:
    desired_cleanup_options_by_region = get_desired_cleanup_options_by_region(
        test_cloudwatch_account
    )
    assert len(desired_cleanup_options_by_region) == 1
    assert len(desired_cleanup_options_by_region["us-east-1"]) == 2


def setup_mocks(
    mocker: MockerFixture,
    aws_accounts: Iterable[AWSAccountV1],
    log_groups: list[dict],
    tags: dict[str, Any],
    utcnow: datetime = datetime.now(UTC),  # noqa: B008
) -> MagicMock:
    mocked_gql_api = create_autospec(GqlApi)
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.gql"
    ).get_api.return_value = mocked_gql_api
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.get_aws_accounts",
        return_value=aws_accounts,
    )
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.queries.get_secret_reader_settings",
        return_value={},
    )
    mocked_datetime = mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.datetime",
        wraps=datetime,
    )
    mocked_datetime.now.return_value = utcnow
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
    test_cloudwatch_account: AWSAccountV1,
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
        test_cloudwatch_account.name,
        log_group_with_unset_retention["arn"],
        "us-east-1",
    )

    mocked_aws_api.create_cloudwatch_tag.assert_called_once_with(
        test_cloudwatch_account.name,
        log_group_with_unset_retention["arn"],
        {"managed_by_integration": "aws_cloudwatch_log_retention"},
        "us-east-1",
    )

    mocked_aws_api.set_cloudwatch_log_retention.assert_called_once_with(
        test_cloudwatch_account.name,
        "group-without-retention",
        90,
        "us-east-1",
    )


@pytest.fixture
def log_group_with_unset_retention_and_matching_name() -> dict[str, Any]:
    return {
        "logGroupName": "some-path-group-without-retention",
        "storedBytes": 0,
        "creationTime": 1433189500783,
        "arn": "arn:aws:logs:us-west-2:0123456789012:log-group:some-path-group-without-retention:*",
    }


def test_run_with_unset_retention_log_group_and_matching_cleanup(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
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
        test_cloudwatch_account.name,
        log_group_with_unset_retention_and_matching_name["arn"],
        "us-east-1",
    )

    mocked_aws_api.create_cloudwatch_tag.assert_called_once_with(
        test_cloudwatch_account.name,
        log_group_with_unset_retention_and_matching_name["arn"],
        {"managed_by_integration": "aws_cloudwatch_log_retention"},
        "us-east-1",
    )

    mocked_aws_api.set_cloudwatch_log_retention.assert_called_once_with(
        test_cloudwatch_account.name,
        "some-path-group-without-retention",
        30,
        "us-east-1",
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
    test_cloudwatch_account: AWSAccountV1,
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
    test_cloudwatch_account: AWSAccountV1,
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
        test_cloudwatch_account.name,
        log_group_with_unset_retention["arn"],
        "us-east-1",
    )
    mocked_aws_api.delete_cloudwatch_log_group.assert_not_called()
    mocked_aws_api.create_cloudwatch_tag.assert_not_called()
    mocked_aws_api.set_cloudwatch_log_retention.assert_not_called()


@pytest.fixture
def log_group_with_empty_stored_bytes() -> dict[str, Any]:
    return {
        "logGroupName": "some-other-path-empty-group",
        "storedBytes": 0,
        "retentionInDays": 90,
        "creationTime": 1433189500783,
        "arn": "arn:aws:logs:us-east-1:0123456789012:log-group:group-without-retention:*",
    }


def test_run_with_empty_log_group_after_retention_in_days(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_empty_stored_bytes: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_empty_stored_bytes],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
        utcnow=datetime.fromtimestamp(
            log_group_with_empty_stored_bytes["creationTime"] / 1000, tz=UTC
        )
        + timedelta(days=61),
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_called_once_with(
        test_cloudwatch_account.name,
        log_group_with_empty_stored_bytes["arn"],
        "us-east-1",
    )
    mocked_aws_api.delete_cloudwatch_log_group.assert_called_once_with(
        test_cloudwatch_account.name,
        log_group_with_empty_stored_bytes["logGroupName"],
        "us-east-1",
    )
    mocked_aws_api.create_cloudwatch_tag.assert_not_called()
    mocked_aws_api.set_cloudwatch_log_retention.assert_not_called()


def test_run_with_empty_log_group_before_retention_in_days(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_empty_stored_bytes: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, Any],
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_empty_stored_bytes],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
        utcnow=datetime.fromtimestamp(
            log_group_with_empty_stored_bytes["creationTime"] / 1000, tz=UTC
        )
        + timedelta(days=59),
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_group_tags.assert_called_once_with(
        test_cloudwatch_account.name,
        log_group_with_empty_stored_bytes["arn"],
        "us-east-1",
    )
    mocked_aws_api.delete_cloudwatch_log_group.assert_not_called()
    mocked_aws_api.create_cloudwatch_tag.assert_not_called()
    mocked_aws_api.set_cloudwatch_log_retention.assert_called_once_with(
        test_cloudwatch_account.name,
        "some-other-path-empty-group",
        60,
        "us-east-1",
    )


@pytest.fixture
def account_with_disabled_integration(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "path": "/aws/some/path/account.yml",
            "name": "some-account-name",
            "uid": string.digits,
            "terraformUsername": None,
            "consoleUrl": "https://some-url.com/console",
            "resourcesDefaultRegion": "us-east-1",
            "supportedDeploymentRegions": None,
            "providerVersion": "3.14.159",
            "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
            "automationToken": {
                "path": "app-sre/some/path/config",
                "field": "all",
                "version": None,
                "format": None,
            },
            "enableDeletion": None,
            "deletionApprovals": None,
            "disable": {
                "integrations": ["aws-cloudwatch-log-retention"],
            },
            "deleteKeys": None,
            "premiumSupport": True,
            "ecrs": None,
            "partition": None,
            "cleanup": [
                {
                    "provider": "cloudwatch",
                    "regex": "some-path*",
                    "retention_in_days": 30,
                    "delete_empty_log_group": None,
                    "region": None,
                },
                {
                    "provider": "cloudwatch",
                    "regex": "some-other-path*",
                    "retention_in_days": 60,
                    "delete_empty_log_group": True,
                    "region": "us-east-1",
                },
            ],
        },
    )


def test_run_with_disabled_integration_account(
    mocker: MockerFixture,
    account_with_disabled_integration: AWSAccountV1,
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[account_with_disabled_integration],
        log_groups=[],
        tags={},
    )

    run(dry_run=False, thread_pool_size=1)

    mocked_aws_api.get_cloudwatch_log_groups.assert_not_called()


@pytest.fixture
def test_cloudwatch_account_with_multiple_regions(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
            "automationToken": {
                "path": "app-sre/some/path/config",
                "field": "all",
                "version": None,
                "format": None,
            },
            "cleanup": [
                {
                    "provider": "cloudwatch",
                    "regex": "some-path*",
                    "retention_in_days": 30,
                    "delete_empty_log_group": None,
                    "region": None,
                },
                {
                    "provider": "cloudwatch",
                    "regex": "some-other-path*",
                    "retention_in_days": 60,
                    "delete_empty_log_group": True,
                    "region": "us-west-2",
                },
            ],
            "name": "account-name-with-multiple_regions",
            "uid": string.digits,
            "resourcesDefaultRegion": "us-east-1",
        },
    )


def test_run_with_multiple_regions_account(
    mocker: MockerFixture,
    test_cloudwatch_account_with_multiple_regions: AWSAccountV1,
) -> None:
    mocked_aws_api = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account_with_multiple_regions],
        log_groups=[],
        tags={},
    )

    run(dry_run=False, thread_pool_size=1)

    assert mocked_aws_api.get_cloudwatch_log_groups.call_count == 2
    calls = mocked_aws_api.get_cloudwatch_log_groups.call_args_list
    called_regions = {call[0][1] for call in calls}
    assert called_regions == {"us-east-1", "us-west-2"}
