import pytest

from reconcile.utils.aws_api import AWSApi
from reconcile.utils.terrascript_aws_client import TerrascriptClient


@pytest.fixture
def default_region():
    return "default-region"


@pytest.fixture
def tf_bucket_region():
    return "tf-bucket-region"


@pytest.fixture
def accounts(default_region):
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


@pytest.fixture
def secret(tf_bucket_region):
    return {
        "aws_access_key_id": "key_id",
        "aws_secret_access_key": "access_key",
        "region": tf_bucket_region,
        "bucket": "tf-bucket-name",
        "_key": "tf_key.tfstate",
    }


@pytest.fixture
def aws_api(accounts, secret, mocker):
    mock_secret_reader = mocker.patch(
        "reconcile.utils.aws_api.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = secret
    return AWSApi(1, accounts, init_users=False)


@pytest.fixture
def terrascript(accounts, secret, mocker):
    mock_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = secret
    return TerrascriptClient("", "", 1, accounts)


def test_wrong_region_aws_api(aws_api, accounts, default_region):
    for a in accounts:
        assert aws_api.sessions[a["name"]].region_name == default_region


def test_wrong_region_terrascript(terrascript, accounts, tf_bucket_region):
    for a in accounts:
        assert terrascript.configs[a["name"]]["region"] == tf_bucket_region


def test_wrong_region_both(
    aws_api, terrascript, accounts, default_region, tf_bucket_region
):
    for a in accounts:
        assert aws_api.sessions[a["name"]].region_name == default_region
        assert terrascript.configs[a["name"]]["region"] == tf_bucket_region
