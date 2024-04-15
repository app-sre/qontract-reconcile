from collections.abc import Callable
from textwrap import dedent
from unittest.mock import MagicMock

from dateutil import parser
from pytest_mock import MockerFixture

from reconcile.gql_definitions.terraform_init.aws_accounts import AWSAccountV1
from reconcile.terraform_init import integration
from reconcile.terraform_init.integration import TerraformInitIntegration


def test_terraform_init_integration_early_exit(
    query_func: Callable, intg: TerraformInitIntegration
) -> None:
    early_exit_state = intg.get_early_exit_desired_state(query_func)
    assert "accounts" in early_exit_state


def test_terraform_init_integration_render_state_collection(
    mocker: MockerFixture,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    datetime_mock = mocker.patch.object(integration, "datetime", autospec=True)
    datetime_mock.now.return_value = parser.parse("2024-09-30T20:15:00+00")
    tmpl = dedent("""
    # test access variables
    {{ account_name }}
    {{ bucket_name }}
    {{ region }}
        {{ timestamp }}
    """)
    output = intg.render_state_collection(
        template=tmpl, bucket_name="bucket_name", account=aws_accounts[0]
    )
    assert output == dedent("""
    # test access variables
    account-1
    bucket_name
    us-east-1
        1727727300
    """)


def test_terraform_init_integration_get_aws_accounts(
    query_func: Callable, intg: TerraformInitIntegration
) -> None:
    accounts = intg.get_aws_accounts(query_func)
    assert len(accounts) == 2
    assert accounts[0].name == "account-1"
    assert accounts[1].name == "account-2"


def test_terraform_init_integration_reconcile_account(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    intg.reconcile_account(
        account_aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        state_collection="template",
        bucket_name="bucket",
        account=aws_accounts[0],
    )
    aws_api.s3.create_bucket.assert_called()
    merge_request_manager.create_merge_request.assert_called()


def test_terraform_init_integration_reconcile_account_dry_run(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    intg.reconcile_account(
        account_aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=True,
        state_collection="template",
        bucket_name="bucket",
        account=aws_accounts[0],
    )
    aws_api.s3.create_bucket.assert_not_called()
    merge_request_manager.create_merge_request.assert_called()
