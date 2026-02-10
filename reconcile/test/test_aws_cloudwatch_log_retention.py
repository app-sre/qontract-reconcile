from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import (
    TYPE_CHECKING,
    Any,
)
from unittest.mock import MagicMock, call, create_autospec

import pytest
from botocore.exceptions import ClientError
from qontract_utils.aws_api_typed.api import AWSStaticCredentials

from reconcile.aws_cloudwatch_log_retention.integration import (
    get_desired_cleanup_options_by_region,
    run,
)
from reconcile.gql_definitions.aws_cloudwatch_log_retention.aws_accounts import (
    AWSAccountV1,
)
from reconcile.gql_definitions.external_resources.external_resources_settings import (
    ExternalResourcesSettingsV1,
)
from reconcile.utils.gql import GqlApi
from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.state import State

TEST_AWS_SECRET_ACCESS_KEY = "some_secret_access_key"
TEST_AWS_ACCESS_KEY_ID = "some_access_key_id"
TEST_AWS_REGION = "us-east-1"

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from pytest_mock import MockerFixture


@pytest.fixture
def test_cloudwatch_account(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "name": "some-account-name",
            "resourcesDefaultRegion": TEST_AWS_REGION,
            "automationToken": {
                "path": "app-sre/some/path/config",
                "field": "all",
                "version": None,
                "format": None,
            },
            "disable": None,
            "organization": {
                "tags": '{"owner": "dev"}',
                "payerAccount": {"organizationAccountTags": '{"env": "test"}'},
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
                    "region": TEST_AWS_REGION,
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
    utcnow: datetime | None = None,
    last_tags: dict[str, Any] | None = None,
) -> dict[str, MagicMock]:
    mocked_gql_api = create_autospec(GqlApi)
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.gql"
    ).get_api.return_value = mocked_gql_api
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.get_app_interface_vault_settings",
    )
    settings = create_autospec(ExternalResourcesSettingsV1)
    settings.default_tags = {
        "default_key": "default_value",
    }
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.get_settings",
        return_value=settings,
    )
    mocked_secret_reader = create_autospec(SecretReader)
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.create_secret_reader",
        return_value=mocked_secret_reader,
    )
    mocked_secret_reader.read_all_secret.return_value = {
        "aws_access_key_id": TEST_AWS_ACCESS_KEY_ID,
        "aws_secret_access_key": TEST_AWS_SECRET_ACCESS_KEY,
    }
    mock_state = create_autospec(State)
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.init_state",
        return_value=mock_state,
    )
    mock_state.__enter__.return_value = mock_state
    mock_state.get.return_value = last_tags or {}
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.get_aws_accounts",
        return_value=aws_accounts,
    )
    mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.utc_now",
        return_value=utcnow or datetime.now(UTC),
    )
    aws_api = mocker.patch(
        "reconcile.aws_cloudwatch_log_retention.integration.AWSApi",
        autospec=True,
    )
    aws_api_logs = aws_api.return_value.__enter__.return_value.logs
    aws_api_logs.get_log_groups.return_value = iter(log_groups)
    aws_api_logs.get_tags.return_value = tags
    aws_api_logs.client.exceptions.ClientError = ClientError
    return {
        "aws_api": aws_api,
        "aws_api_logs": aws_api_logs,
        "state": mock_state,
    }


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
def stale_tags() -> dict[str, str]:
    return {
        "default_key": "default_value",
        "managed_by_integration": "aws_cloudwatch_log_retention",
        "owner": "dev",
        "env": "stale",
    }


@pytest.fixture
def managed_by_aws_cloudwatch_log_retention_tags() -> dict[str, str]:
    return {
        "default_key": "default_value",
        "managed_by_integration": "aws_cloudwatch_log_retention",
        "owner": "dev",
        "env": "test",
    }


@pytest.fixture
def additional_tags() -> dict[str, str]:
    return {
        "default_key": "default_value",
        "managed_by_integration": "aws_cloudwatch_log_retention",
        "owner": "dev",
        "env": "test",
        "additional": "value",
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
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
    empty_tags: dict[str, Any],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention],
        tags=empty_tags,
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_log_groups.assert_called_once_with()
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_unset_retention["arn"],
    )
    mocks["aws_api_logs"].set_tags.assert_called_once_with(
        log_group_with_unset_retention["arn"],
        managed_by_aws_cloudwatch_log_retention_tags,
    )
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_called_once_with(
        "group-without-retention",
        90,
    )
    mocks["state"].add.assert_called_once_with(
        "tags.json",
        {test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags},
        force=True,
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
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
    empty_tags: dict[str, Any],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention_and_matching_name],
        tags=empty_tags,
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_unset_retention_and_matching_name["arn"],
    )

    mocks["aws_api_logs"].set_tags.assert_called_once_with(
        log_group_with_unset_retention_and_matching_name["arn"],
        managed_by_aws_cloudwatch_log_retention_tags,
    )
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_called_once_with(
        "some-path-group-without-retention",
        30,
    )
    mocks["state"].add.assert_called_once_with(
        "tags.json",
        {test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags},
        force=True,
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


def test_run_with_matching_retention_log_group_and_last_tags(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_desired_retention: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_desired_retention],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
        last_tags={
            test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags,
        },
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_not_called()
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_not_called()


def test_run_with_matching_retention_log_group_and_stale_tags(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_desired_retention: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
    stale_tags: dict[str, str],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_desired_retention],
        tags=stale_tags,
        last_tags={
            test_cloudwatch_account.name: stale_tags,
        },
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_desired_retention["arn"],
    )
    mocks["aws_api_logs"].set_tags.assert_called_once_with(
        log_group_with_desired_retention["arn"],
        managed_by_aws_cloudwatch_log_retention_tags,
    )
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_called_once_with(
        "tags.json",
        {test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags},
        force=True,
    )


def test_run_with_matching_retention_log_group_and_stale_tags_on_error(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_desired_retention: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
    stale_tags: dict[str, str],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_desired_retention],
        tags=stale_tags,
        last_tags={
            test_cloudwatch_account.name: stale_tags,
        },
    )
    mocks["aws_api_logs"].get_tags.side_effect = ClientError(
        error_response={
            "Error": {
                "Code": "ThrottlingException",
            },
        },
        operation_name="ListTagsForResource",
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_desired_retention["arn"],
    )
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_not_called()


def test_run_with_matching_retention_log_group_with_deleted_desired_tags(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_desired_retention: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
    additional_tags: dict[str, str],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_desired_retention],
        tags=additional_tags | {"aws:cloudformation:stack-name": "some-stack"},
        last_tags={
            test_cloudwatch_account.name: additional_tags,
        },
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_desired_retention["arn"],
    )
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_called_once_with(
        log_group_with_desired_retention["arn"],
        {"additional"},
    )
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_called_once_with(
        "tags.json",
        {test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags},
        force=True,
    )


def test_run_with_log_group_managed_by_terraform_resources(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_unset_retention: dict[str, Any],
    managed_by_terraform_resources_tags: dict[str, str],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, str],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_unset_retention],
        tags=managed_by_terraform_resources_tags,
        last_tags={
            test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags,
        },
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_unset_retention["arn"],
    )
    mocks["aws_api_logs"].delete_log_group.assert_not_called()
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_not_called()


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
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_empty_stored_bytes],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
        last_tags={
            test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags,
        },
        utcnow=datetime.fromtimestamp(
            log_group_with_empty_stored_bytes["creationTime"] / 1000, tz=UTC
        )
        + timedelta(days=61),
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_empty_stored_bytes["arn"],
    )
    mocks["aws_api_logs"].delete_log_group.assert_called_once_with(
        log_group_with_empty_stored_bytes["logGroupName"],
    )
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_not_called()
    mocks["state"].add.assert_not_called()


def test_run_with_empty_log_group_before_retention_in_days(
    mocker: MockerFixture,
    test_cloudwatch_account: AWSAccountV1,
    log_group_with_empty_stored_bytes: dict[str, Any],
    managed_by_aws_cloudwatch_log_retention_tags: dict[str, Any],
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[test_cloudwatch_account],
        log_groups=[log_group_with_empty_stored_bytes],
        tags=managed_by_aws_cloudwatch_log_retention_tags,
        last_tags={
            test_cloudwatch_account.name: managed_by_aws_cloudwatch_log_retention_tags,
        },
        utcnow=datetime.fromtimestamp(
            log_group_with_empty_stored_bytes["creationTime"] / 1000, tz=UTC
        )
        + timedelta(days=59),
    )

    run(dry_run=False)

    mocks["aws_api"].assert_called_once_with(
        AWSStaticCredentials(
            access_key_id=TEST_AWS_ACCESS_KEY_ID,
            secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
            region=TEST_AWS_REGION,
        )
    )
    mocks["aws_api_logs"].get_tags.assert_called_once_with(
        log_group_with_empty_stored_bytes["arn"],
    )
    mocks["aws_api_logs"].delete_log_group.assert_not_called()
    mocks["aws_api_logs"].set_tags.assert_not_called()
    mocks["aws_api_logs"].delete_tags.assert_not_called()
    mocks["aws_api_logs"].put_retention_policy.assert_called_once_with(
        "some-other-path-empty-group",
        60,
    )
    mocks["state"].add.assert_not_called()


@pytest.fixture
def account_with_disabled_integration(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
            "name": "some-account-name",
            "resourcesDefaultRegion": "us-east-1",
            "automationToken": {
                "path": "app-sre/some/path/config",
                "field": "all",
                "version": None,
                "format": None,
            },
            "disable": {
                "integrations": ["aws-cloudwatch-log-retention"],
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
                    "region": "us-east-1",
                },
            ],
        },
    )


def test_run_with_disabled_integration_account(
    mocker: MockerFixture,
    account_with_disabled_integration: AWSAccountV1,
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[account_with_disabled_integration],
        log_groups=[],
        tags={},
    )

    run(dry_run=False)

    mocks["aws_api"].assert_not_called()


@pytest.fixture
def cloudwatch_account_with_multiple_regions(
    gql_class_factory: Callable[..., AWSAccountV1],
) -> AWSAccountV1:
    return gql_class_factory(
        AWSAccountV1,
        {
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
            "resourcesDefaultRegion": "us-east-1",
        },
    )


def test_run_with_multiple_regions_account(
    mocker: MockerFixture,
    cloudwatch_account_with_multiple_regions: AWSAccountV1,
) -> None:
    mocks = setup_mocks(
        mocker,
        aws_accounts=[cloudwatch_account_with_multiple_regions],
        log_groups=[],
        tags={},
    )

    run(dry_run=False)

    assert mocks["aws_api"].call_count == 2
    mocks["aws_api"].assert_has_calls(
        [
            call(
                AWSStaticCredentials(
                    access_key_id=TEST_AWS_ACCESS_KEY_ID,
                    secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
                    region="us-east-1",
                )
            ),
            call(
                AWSStaticCredentials(
                    access_key_id=TEST_AWS_ACCESS_KEY_ID,
                    secret_access_key=TEST_AWS_SECRET_ACCESS_KEY,
                    region="us-west-2",
                )
            ),
        ],
        any_order=True,
    )
