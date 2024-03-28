import logging
import random
from collections.abc import Callable
from typing import Any

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.fragments.aws_vpc_request import (
    VPCRequest,
)
from reconcile.status import ExitCodes
from reconcile.terraform_vpc_resources import (
    TerraformVpcResources,
    TerraformVpcResourcesParams,
)


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
    }


def vpc_request_dict() -> dict[str, Any]:
    return {
        "name": "some-name",
        "account": account_dict("some-account"),
        "region": "us-east-1",
        "cidr_block": {
            "networkAddress": "10.0.0.0/16",
        },
    }


@pytest.fixture
def mock_gql(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.gql",
        autospec=True,
    )


@pytest.fixture
def mock_app_interface_vault_settings(mocker: MockerFixture) -> MockerFixture:
    mocked_app_interfafe_vault_settings = mocker.patch(
        "reconcile.terraform_vpc_resources.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_app_interfafe_vault_settings.return_value = AppInterfaceSettingsV1(
        vault=True
    )
    return mocked_app_interfafe_vault_settings


@pytest.fixture
def mock_create_secret_reader(mocker: MockerFixture) -> MockerFixture:
    return mocker.patch(
        "reconcile.terraform_vpc_resources.create_secret_reader", autospec=True
    )


def test_log_message_for_no_vpc_requests(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    gql_class_factory: Callable,
    mock_gql: MockerFixture,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
) -> None:
    # Mock a query response without any accounts
    mocked_query = mocker.patch(
        "reconcile.terraform_vpc_resources.get_aws_vpc_requests", autospec=True
    )
    mocked_query.return_value = []

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        TerraformVpcResources(params).run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert ["No VPC requests found, nothing to do."] == [
        rec.message for rec in caplog.records
    ]


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
        "reconcile.terraform_vpc_resources.get_aws_vpc_requests", autospec=True
    )
    mocked_query.return_value = [gql_class_factory(VPCRequest, vpc_request_dict())]

    account_name = "not-related-account"
    params = TerraformVpcResourcesParams(
        account_name=account_name, print_to_file=None, thread_pool_size=1
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        TerraformVpcResources(params).run(dry_run=True)
    assert sample.value.code == ExitCodes.ERROR
    assert [
        f"The account {account_name} doesn't have any managed vpc. Verify your input"
    ] == [rec.message for rec in caplog.records]
