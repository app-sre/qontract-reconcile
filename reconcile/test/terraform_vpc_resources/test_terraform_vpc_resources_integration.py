import logging
import random
from collections.abc import Callable
from typing import Any
from unittest.mock import call

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
    PlanStepError,
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
def mock_gql(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.integration.gql",
        autospec=True,
    )


@pytest.fixture
def mock_app_interface_vault_settings(mocker: MockerFixture) -> MockerFixture:
    mocked_app_interfafe_vault_settings = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_app_interfafe_vault_settings.return_value = AppInterfaceSettingsV1(
        vault=True
    )
    return mocked_app_interfafe_vault_settings


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.integration.create_secret_reader",
        autospec=True,
    )


@pytest.fixture
def mock_terraform_client(mocker: MockerFixture) -> MockerFixture:
    mocked_tf_client = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.TerraformClient", autospec=True
    )
    mocked_tf_client.return_value.plan.return_value = False, None
    return mocked_tf_client


def secret_reader_side_effect(*args: Any) -> dict[str, Any] | None:
    """Mocking a secret reader call for aws account credentials"""
    if {
        "path": "some-path",
        "field": "some-field",
        "version": None,
        "format": None,
    } == args[0]:
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
    mock_gql: MockerFixture,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
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


def test_plan_step_error_exception(
    mocker: MockerFixture,
    mock_gql: pytest.LogCaptureFixture,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
    mock_terraform_client: MockerFixture,
) -> None:
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_aws_vpc_requests",
        autospec=True,
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_dict())]

    secret_reader = mocker.Mock(SecretReaderBase)
    secret_reader.read_all.side_effect = secret_reader_side_effect

    mock_create_secret_reader.return_value = secret_reader

    # Silumating errors in the plan step, first return value is detection of deletions,
    # second return value is detection of errors
    mock_terraform_client.return_value.plan.return_value = True, True

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )

    with pytest.raises(PlanStepError) as exeption:
        TerraformVpcResources(params).run(dry_run=True)
    assert str(exeption.value) == "Errors in terraform plan step, please verify output."


def test_dry_run(
    mocker: MockerFixture,
    mock_gql: pytest.LogCaptureFixture,
    gql_class_factory: Callable,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
    mock_terraform_client: MockerFixture,
) -> None:
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.integration.get_aws_vpc_requests",
        autospec=True,
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_dict())]

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
