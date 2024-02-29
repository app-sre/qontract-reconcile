import logging

import pytest

import reconcile.terraform_vpc_resources as integ
from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.terraform_vpc_resources.vpc_resources_aws_accounts import (
    AWSAccountV1,
    AWSTerraformStateIntegrationsV1,
    TerraformStateAWSV1,
    VPCResourcesAWSAccountsQueryData,
)
from reconcile.status import ExitCodes


@pytest.fixture
def query_data():
    return VPCResourcesAWSAccountsQueryData(
        accounts=[
            AWSAccountV1(
                name="some-account",
                terraformState=TerraformStateAWSV1(
                    integrations=[
                        AWSTerraformStateIntegrationsV1(
                            key="some-key",
                            integration="some-integration",
                        ),
                    ]
                ),
            ),
            AWSAccountV1(
                name="some-other-account",
                terraformState=TerraformStateAWSV1(
                    integrations=[
                        AWSTerraformStateIntegrationsV1(
                            key="terraform-vpc-resouces.tf.json",
                            integration="terraform-vpc-resources",
                        ),
                    ]
                ),
            ),
        ]
    )


@pytest.fixture
def mock_gql(mocker):
    return mocker.patch(
        "reconcile.terraform_vpc_resources.gql",
        autospec=True,
    )


@pytest.fixture
def mock_app_interface_vault_settings(mocker):
    mocked_app_interfafe_vault_settings = mocker.patch(
        "reconcile.terraform_vpc_resources.get_app_interface_vault_settings",
        autospec=True,
    )
    mocked_app_interfafe_vault_settings.return_value = AppInterfaceSettingsV1(
        vault=True
    )
    return mocked_app_interfafe_vault_settings


@pytest.fixture
def mock_create_secret_reader(mocker):
    return mocker.patch(
        "reconcile.terraform_vpc_resources.create_secret_reader", autospec=True
    )


def test_log_message_for_no_aws_accounts(
    mocker,
    caplog,
    mock_gql,
    mock_app_interface_vault_settings,
    mock_create_secret_reader,
):
    # Mock a query response without any accounts
    mocked_query = mocker.patch("reconcile.terraform_vpc_resources.query_aws_accounts")
    mocked_query.return_value = VPCResourcesAWSAccountsQueryData(accounts=[])

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        integ.run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert ["No AWS accounts found, nothing to do."] == [
        rec.message for rec in caplog.records
    ]


def test_log_message_for_no_accounts_with_related_state(
    mocker,
    caplog,
    mock_gql,
    mock_app_interface_vault_settings,
    mock_create_secret_reader,
):
    # Mock a query with an account that doesn't have the related state
    mocked_query = mocker.patch("reconcile.terraform_vpc_resources.query_aws_accounts")
    mocked_query.return_value = VPCResourcesAWSAccountsQueryData(accounts=[
        AWSAccountV1(
            name="some-account",
            terraformState=TerraformStateAWSV1(
                integrations=[
                    AWSTerraformStateIntegrationsV1(
                        key="some-key",
                        integration="some-integration",
                    ),
                ]
            ),
        )
    ])

    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        integ.run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert ["No AWS accounts with 'terraform-vpc-resources' state found, nothing to do."] == [
        rec.message for rec in caplog.records
    ]