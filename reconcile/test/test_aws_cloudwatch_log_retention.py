from collections.abc import Generator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import boto3
import pytest
from moto import mock_logs
from pytest_mock import MockerFixture

from reconcile.aws_cloudwatch_log_retention.integration import (
    check_cloudwatch_log_group_tag,
    get_app_interface_cloudwatch_retention_period,
)
from reconcile.utils.aws_api import AWSApi

if TYPE_CHECKING:
    from mypy_boto3_logs import CloudWatchLogsClient
else:
    CloudWatchLogsClient = object
    CreateImageResultTypeDef = dict


# -> list[dict[str, Any]]
@pytest.fixture
def accounts():
    return [
        {
            "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
            "automationToken": {
                "path": "path",
            },
            "cleanup": [
                {
                    "provider": "cloudwatch",
                    "regex": "some/path*",
                    "retention_in_days": "90",
                },
                {
                    "provider": "cloudwatch",
                    "regex": "some/other/path*",
                    "retention_in_days": "90",
                },
            ],
            "consoleUrl": "https://some-url.com/console",
            "name": "some-account-name",
            "uid": "0123456789",
            "resourcesDefaultRegion": "default-region",
        }
    ]


@pytest.fixture
def aws_api(accounts, mocker: MockerFixture) -> AWSApi:
    mock_secret_reader = mocker.patch(
        "reconcile.utils.aws_api.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "key_id",
        "aws_secret_access_key": "access_key",
        "region": "tf_state_bucket_region",
    }
    return AWSApi(1, accounts, init_users=False)


@pytest.fixture
def cloudwatchlogs_client() -> Generator[CloudWatchLogsClient, None, None]:
    with mock_logs():
        yield boto3.client("logs", region_name="us-east-1")


@pytest.fixture(autouse=True)
def log_group_tf_tag(cloudwatchlogs_client: CloudWatchLogsClient):
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


def test_get_app_interface_cloudwatch_retention_period():
    test_cloudwatch_acct = {
        "accountOwners": [{"email": "some-email@email.com", "name": "Some Team"}],
        "cleanup": [
            {
                "provider": "cloudwatch",
                "regex": "some/path*",
                "retention_in_days": "90",
            },
            {
                "provider": "cloudwatch",
                "regex": "some/other/path*",
                "retention_in_days": "90",
            },
        ],
        "consoleUrl": "https://some-url.com/console",
        "name": "some-account-name",
        "uid": "0123456789",
    }
    refined_cloudwatch_list = get_app_interface_cloudwatch_retention_period(
        test_cloudwatch_acct
    )
    assert len(refined_cloudwatch_list) == 2


# def test_get_log_tag_groups(log_group_tf_tag, cloudwatchlogs_client):
#     boto3.client = MagicMock()
#     tag_result = log_group_tf_tag
#     result = check_cloudwatch_log_group_tag(tag_result, cloudwatchlogs_client)
#     assert len(result) == 1
