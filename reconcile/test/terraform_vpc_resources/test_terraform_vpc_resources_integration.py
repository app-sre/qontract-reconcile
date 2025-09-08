import json
import logging
import random
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, call

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.fragments.aws_vpc_request import (
    VPCRequest,
)
from reconcile.status import ExitCodes
from reconcile.terraform_vpc_resources.integration import (
    TerraformVpcResources,
    TerraformVpcResourcesParams,
)
from reconcile.utils.secret_reader import SecretReaderBase


def account_dict(name: str) -> dict[str, Any]:
    # Generates a 12 digit uid using random
    uid = "".join(str(random.randint(0, 9)) for _ in range(12))

    return {
        "name": name,
        "uid": uid,
        "automationToken": {
            "path": "some-path",
            "field": "some-field",
            "version": None,
            "format": None,
        },
        "terraformState": {
            "provider": "s3",
            "bucket": "integration-bucket",
            "integrations": [
                {
                    "integration": "terraform-vpc-resources",
                    "key": "qontract-reconcile-terraform-vpc-resources.tfstate",
                }
            ],
        },
    }


def vpc_request_dict() -> dict[str, Any]:
    return {
        "identifier": "some-identifier",
        "account": account_dict("some-account"),
        "region": "us-east-1",
        "cidr_block": {
            "networkAddress": "10.0.0.0/16",
        },
    }


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.integration.gql",
        autospec=True,
    )


@pytest.fixture
def mock_app_interface_vault_settings(mocker: MockerFixture) -> MagicMock:
    mocked_app_interfafe_vault_settings = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_app_interfafe_vault_settings.return_value = AppInterfaceSettingsV1(
        vault=True
    )
    return mocked_app_interfafe_vault_settings


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> MagicMock:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.integration.create_secret_reader",
        autospec=True,
    )


@pytest.fixture
def mock_terraform_client(mocker: MockerFixture) -> MagicMock:
    mocked_tf_client = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.TerraformClient", autospec=True
    )
    mocked_tf_client.return_value.safe_plan.return_value = None
    return mocked_tf_client


def secret_reader_side_effect(*args: Any) -> dict[str, Any] | None:
    """Mocking a secret reader call for aws account credentials"""
    if args[0] == {
        "path": "some-path",
        "field": "some-field",
        "version": None,
        "format": None,
    }:
        return {
            "aws_access_key_id": "key_id",
            "aws_secret_access_key": "access_key",
            "key": "qontract-reconcile.tfstate",
            "profile": "terraform-aws02",
            "terraform-resources-wreapper_key": "qontract-reconcile.tfstate",
        }

    # Just to make testing this easier and fail faster
    raise Exception("Argument error")


def test_log_message_for_accounts_having_vpc_requests(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    mock_gql: MagicMock,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MagicMock,
    mock_create_secret_reader: MagicMock,
) -> None:
    # Mock a query with an account that doesn't have the related state
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_aws_vpc_requests",
        autospec=True,
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_dict())]

    account_name = "not-related-account"
    params = TerraformVpcResourcesParams(
        account_name=account_name, print_to_file=None, thread_pool_size=1
    )
    with (
        caplog.at_level(logging.DEBUG),
        pytest.raises(SystemExit) as sample,
    ):
        TerraformVpcResources(params).run(dry_run=True)

    error_msg = (
        f"The account {account_name} doesn't have any managed vpc. Verify your input"
    )
    assert sample.value.code == ExitCodes.SUCCESS
    assert [error_msg] == [rec.message for rec in caplog.records]


def test_dry_run(
    mocker: MockerFixture,
    mock_gql: MagicMock,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MagicMock,
    mock_create_secret_reader: MagicMock,
    mock_terraform_client: MagicMock,
) -> None:
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_aws_vpc_requests",
        autospec=True,
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_dict())]
    mocked_get_settings = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_settings"
    )
    mocked_get_settings.return_value.default_tags = None

    secret_reader = mocker.Mock(SecretReaderBase)
    secret_reader.read_all.side_effect = secret_reader_side_effect

    mock_create_secret_reader.return_value = secret_reader

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )

    with pytest.raises(SystemExit) as sample:
        TerraformVpcResources(params).run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert mock_terraform_client.called is True
    assert call().apply() not in mock_terraform_client.method_calls


def test_vpc_and_subnet_tags(
    mocker: MockerFixture,
    mock_gql: MagicMock,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MagicMock,
    mock_create_secret_reader: MagicMock,
    mock_terraform_client: MagicMock,
) -> None:
    """Test that VPC tags are properly processed and included in outputs."""
    # Setup VPC request with custom VPC tags
    vpc_request_data = vpc_request_dict()
    vpc_request_data["vpc_tags"] = json.dumps({
        "Environment": "test",
        "Team": "platform",
        "Project": "vpc-resources",
    })
    vpc_request_data["subnets"] = {
        "private": ["10.0.1.0/24", "10.0.2.0/24"],
        "public": ["10.0.10.0/24", "10.0.20.0/24"],
        "availability_zones": ["us-east-1a", "us-east-1b"],
        "private_subnet_tags": json.dumps({"Type": "private"}),
        "public_subnet_tags": json.dumps({"Type": "public"}),
    }

    # Mock the query to return our VPC request with tags
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_aws_vpc_requests",
        autospec=True,
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_data)]

    # Mock secret reader
    secret_reader = mocker.Mock(SecretReaderBase)
    secret_reader.read_all.side_effect = secret_reader_side_effect
    mock_create_secret_reader.return_value = secret_reader

    # Mock terraform client outputs
    mock_terraform_client.return_value.outputs = {
        "some-account": {
            "some-identifier-vpc_id": {"value": "vpc-12345"},
            "some-identifier-private_subnets": {
                "value": ["subnet-private1", "subnet-private2"]
            },
            "some-identifier-public_subnets": {
                "value": ["subnet-public1", "subnet-public2"]
            },
        }
    }

    # Mock VCS and MR manager dependencies
    mock_mr_manager = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.MergeRequestManager",
        autospec=True,
    )
    mock_mr_manager.return_value._fetch_managed_open_merge_requests.return_value = None
    mock_mr_manager.return_value.create_merge_request.return_value = None

    # Mock template retrieval
    mock_gql.get_api.return_value.get_template.return_value = {
        "template": "vpc_id: {{ static.vpc_id }}\nvpc_tags: {{ static.vpc_tags }}"
    }

    # Mock typed queries
    mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_github_orgs", return_value=[]
    )
    mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_gitlab_instances",
        return_value=[],
    )
    mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_app_interface_repo_url",
        return_value="https://github.com/test/repo",
    )

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )

    # Create integration instance and access private method for testing
    integration = TerraformVpcResources(params)

    # Test the _handle_outputs method directly to verify VPC tags processing
    vpc_requests = [gql_class_factory(VPCRequest, vpc_request_data)]
    terraform_outputs = {
        "some-account": {
            "some-identifier-vpc_id": {"value": "vpc-12345"},
            "some-identifier-private_subnets": {
                "value": ["subnet-private1", "subnet-private2"]
            },
            "some-identifier-public_subnets": {
                "value": ["subnet-public1", "subnet-public2"]
            },
        }
    }

    handled_outputs = integration._handle_outputs(vpc_requests, terraform_outputs)

    # Verify VPC tags are correctly processed
    assert "some-identifier" in handled_outputs
    vpc_output = handled_outputs["some-identifier"]
    assert "static" in vpc_output
    static_data = vpc_output["static"]

    # Check that VPC tags are properly included
    assert "vpc_tags" in static_data
    expected_vpc_tags = {
        "Environment": "test",
        "Team": "platform",
        "Project": "vpc-resources",
    }
    assert static_data["vpc_tags"] == expected_vpc_tags

    # Verify other expected fields are present
    assert static_data["vpc_id"] == "vpc-12345"
    assert static_data["account_name"] == "some-account"
    assert static_data["region"] == "us-east-1"
    assert static_data["cidr_block"] == "10.0.0.0/16"
    assert static_data["identifier"] == "some-identifier"

    # Verify subnet configuration and tags
    assert "subnets" in static_data
    subnets = static_data["subnets"]
    assert subnets["private"] == ["subnet-private1", "subnet-private2"]
    assert subnets["public"] == ["subnet-public1", "subnet-public2"]

    # Explicitly test that subnet tag keys exist in static data
    assert "private_subnet_tags" in subnets
    assert "public_subnet_tags" in subnets

    # Check that default subnet tags are merged with custom tags
    expected_private_tags = {"kubernetes.io/role/internal-elb": "1", "Type": "private"}
    expected_public_tags = {"kubernetes.io/role/elb": "1", "Type": "public"}
    assert subnets["private_subnet_tags"] == expected_private_tags
    assert subnets["public_subnet_tags"] == expected_public_tags

    expected_availability_zones = ["us-east-1a", "us-east-1b"]
    assert subnets["availability_zones"] == expected_availability_zones
