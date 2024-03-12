import logging

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.app_interface_vault_settings import (
    AppInterfaceSettingsV1,
)
from reconcile.gql_definitions.terraform_vpc_resources.vpc_resources_aws_accounts import (
    AWSAccountV1,
    AWSTerraformStateIntegrationsV1,
    TerraformStateAWSV1,
    VaultSecretV1,
    VPCResourcesAWSAccountsQueryData,
)
from reconcile.status import ExitCodes
from reconcile.terraform_vpc_resources import (
    TerraformVpcResources,
    TerraformVpcResourcesParams,
)


@pytest.fixture
def query_data() -> VPCResourcesAWSAccountsQueryData:
    return VPCResourcesAWSAccountsQueryData(
        accounts=[
            AWSAccountV1(
                name="some-account",
                uid="some-uid",
                automationToken=VaultSecretV1(
                    path="some-path",
                    field="some-field",
                    version=None,
                    format=None,
                ),
                providerVersion="3.76.1",
                resourcesDefaultRegion="us-east-1",
                supportedDeploymentRegions=["us-east-1", "us-east-2"],
                terraformState=TerraformStateAWSV1(
                    bucket="some-bucket",
                    region="us-east-1",
                    integrations=[
                        AWSTerraformStateIntegrationsV1(
                            key="some-key",
                            integration="some-integration",
                        ),
                    ],
                ),
            ),
            AWSAccountV1(
                name="some-other-account",
                uid="some-uid",
                automationToken=VaultSecretV1(
                    path="some-path",
                    field="some-field",
                    version=None,
                    format=None,
                ),
                providerVersion="3.76.1",
                resourcesDefaultRegion="us-east-1",
                supportedDeploymentRegions=["us-east-1", "us-east-2"],
                terraformState=TerraformStateAWSV1(
                    bucket="some-bucket",
                    region="us-east-1",
                    integrations=[
                        AWSTerraformStateIntegrationsV1(
                            key="terraform-vpc-resouces.tf.json",
                            integration="terraform-vpc-resources",
                        ),
                    ],
                ),
            ),
        ]
    )


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


def test_log_message_for_no_aws_accounts(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    mock_gql: MockerFixture,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
) -> None:
    # Mock a query response without any accounts
    mocked_query = mocker.patch("reconcile.terraform_vpc_resources.query_aws_accounts")
    mocked_query.return_value = VPCResourcesAWSAccountsQueryData(accounts=[])

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        TerraformVpcResources(params).run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert ["No AWS accounts found, nothing to do."] == [
        rec.message for rec in caplog.records
    ]


def test_log_message_for_no_accounts_with_related_state(
    mocker: MockerFixture,
    caplog: pytest.LogCaptureFixture,
    mock_gql: MockerFixture,
    mock_app_interface_vault_settings: MockerFixture,
    mock_create_secret_reader: MockerFixture,
) -> None:
    # Mock a query with an account that doesn't have the related state
    mocked_query = mocker.patch("reconcile.terraform_vpc_resources.query_aws_accounts")
    mocked_query.return_value = VPCResourcesAWSAccountsQueryData(
        accounts=[
            AWSAccountV1(
                name="some-account",
                uid="some-uid",
                providerVersion="3.76.1",
                resourcesDefaultRegion="us-east-1",
                supportedDeploymentRegions=["us-east-1", "us-east-2"],
                automationToken=VaultSecretV1(
                    path="some-path",
                    field="some-field",
                    version=None,
                    format=None,
                ),
                terraformState=TerraformStateAWSV1(
                    bucket="some-bucket",
                    region="us-east-1",
                    integrations=[
                        AWSTerraformStateIntegrationsV1(
                            key="some-key",
                            integration="some-integration",
                        ),
                    ],
                ),
            )
        ]
    )

    params = TerraformVpcResourcesParams(
        account_name=None, print_to_file=None, thread_pool_size=1
    )
    with caplog.at_level(logging.INFO), pytest.raises(SystemExit) as sample:
        TerraformVpcResources(params).run(dry_run=True)
    assert sample.value.code == ExitCodes.SUCCESS
    assert [
        "No AWS accounts with 'terraform-vpc-resources' state found, nothing to do."
    ] == [rec.message for rec in caplog.records]
