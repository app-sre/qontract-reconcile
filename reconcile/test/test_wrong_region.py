from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terrascript_aws_client import TerrascriptClient


@pytest.fixture
def default_region() -> str:
    return "default-region"


@pytest.fixture
def tf_bucket_region() -> str:
    return "tf-bucket-region"


Accounts = list[dict[str, Any]]


@pytest.fixture
def accounts(default_region: str) -> Accounts:
    return [
        {
            "name": "some-account",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": default_region,
            "supportedDeploymentRegions": [default_region],
            "providerVersion": "1.2.3",
            "uid": "123",
            "terraformState": {},
        }
    ]


Secret = dict[str, str]


@pytest.fixture
def secret(tf_bucket_region: str) -> Secret:
    return {
        "aws_access_key_id": "key_id",
        "aws_secret_access_key": "access_key",
        "region": tf_bucket_region,
        "bucket": "tf-bucket-name",
        "_key": "tf_key.tfstate",
    }


@pytest.fixture
def aws_api(accounts: Accounts, secret: Secret, mocker: MockerFixture) -> AWSApi:
    mock_secret_reader = mocker.patch(
        "reconcile.utils.aws_api.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = secret
    return AWSApi(1, accounts, init_users=False)


@pytest.fixture
def terrascript(
    accounts: Accounts, secret: Secret, mocker: MockerFixture
) -> TerrascriptClient:
    mock_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = secret
    return TerrascriptClient("", "", 1, accounts)


def test_wrong_region_aws_api(
    aws_api: AWSApi, accounts: Accounts, default_region: str
) -> None:
    for a in accounts:
        assert aws_api.sessions[a["name"]].region_name == default_region


def test_wrong_region_terrascript(
    terrascript: TerrascriptClient, accounts: Accounts, tf_bucket_region: str
) -> None:
    for a in accounts:
        assert terrascript.configs[a["name"]]["region"] == tf_bucket_region


def test_wrong_region_both(
    aws_api: AWSApi,
    terrascript: TerrascriptClient,
    accounts: Accounts,
    default_region: str,
    tf_bucket_region: str,
) -> None:
    for a in accounts:
        assert aws_api.sessions[a["name"]].region_name == default_region
        assert terrascript.configs[a["name"]]["region"] == tf_bucket_region
