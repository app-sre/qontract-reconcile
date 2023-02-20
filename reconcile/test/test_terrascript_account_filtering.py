from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.utils.secret_reader import SecretReader
from reconcile.utils.terrascript_aws_client import TerrascriptClient


@pytest.fixture
def accounts() -> list[dict[str, Any]]:
    return [
        {
            "name": "acc-with-another-integration-disabled",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "us-east-1",
            "supportedDeploymentRegions": ["us-east-1"],
            "providerVersion": "1.2.3",
            "uid": "123",
            "terraformState": {
                "provider": "s3",
                "bucket": "the-bucket",
                "region": "us-east-1",
                "integrations": [
                    {
                        "integration": "terraform-resources",
                        "key": "the-state.tfstate",
                    }
                ],
            },
            "disable": {"integrations": ["another-integration"]},
        },
        {
            "name": "acc-with-terraform-resource-disabled",
            "automationToken": {
                "path": "path",
            },
            "resourcesDefaultRegion": "us-east-1",
            "supportedDeploymentRegions": ["us-east-1"],
            "providerVersion": "1.2.3",
            "uid": "123",
            "terraformState": {
                "provider": "s3",
                "bucket": "another-bucket",
                "region": "us-east-1",
                "integrations": [
                    {
                        "integration": "terraform-resources",
                        "key": "another-state.tfstate",
                    }
                ],
            },
            "disable": {"integrations": ["terraform-resources"]},
        },
    ]


@pytest.fixture
def secret_reader(mocker: MockerFixture) -> SecretReader:
    mock_secret_reader = mocker.patch(
        "reconcile.utils.terrascript_aws_client.SecretReader", autospec=True
    )
    mock_secret_reader.return_value.read_all.return_value = {
        "aws_access_key_id": "key_id",
        "aws_secret_access_key": "access_key",
        "region": "us-east-1",
        "bucket": "tf-bucket-name",
        "_key": "tf_key.tfstate",
    }
    return mock_secret_reader


def test_filter_disabled_accounts_for_integration(
    accounts: list[dict[str, Any]], secret_reader: SecretReader
) -> None:
    ts = TerrascriptClient(
        "terraform_resources", "", 1, accounts, filter_disabled_accounts=True
    )
    assert "acc-with-another-integration-disabled" in ts.accounts
    assert "acc-with-terraform-resource-disabled" not in ts.accounts


def test_dont_filter_disabled_accounts_for_integration(
    accounts: list[dict[str, Any]], secret_reader: SecretReader
) -> None:
    ts = TerrascriptClient(
        "terraform_resources", "", 1, accounts, filter_disabled_accounts=False
    )
    assert "acc-with-another-integration-disabled" in ts.accounts
    assert "acc-with-terraform-resource-disabled" in ts.accounts
