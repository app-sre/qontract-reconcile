import datetime
from collections.abc import Callable
from textwrap import dedent
from unittest.mock import MagicMock, create_autospec

from pytest_mock import MockerFixture

from reconcile.gql_definitions.terraform_init.aws_accounts import AWSAccountV1
from reconcile.terraform_init import integration
from reconcile.terraform_init.integration import TerraformInitIntegration
from reconcile.terraform_init.merge_request_manager import MrData
from reconcile.utils.gql import GqlApi


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
    mocker.patch.object(
        integration,
        "utc_now",
        return_value=datetime.datetime(2024, 9, 30, 20, 15, 0, tzinfo=datetime.UTC),
    )
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
    assert len(accounts) == 3
    assert accounts[0].name == "account-1"
    assert accounts[1].name == "account-2"
    assert accounts[2].name == "terraform-state-already-set"


def test_terraform_init_integration_get_default_tags(
    intg: TerraformInitIntegration,
    external_resource_settings: dict,
) -> None:
    mock_gql_api = create_autospec(GqlApi)
    mock_gql_api.query.return_value = external_resource_settings

    result = intg.get_default_tags(mock_gql_api)

    assert result == {"env": "test"}


def test_terraform_init_integration_reconcile_account_with_new_account(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "account-1")
    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.create_stack.assert_called_once_with(
        stack_name="terraform-account-1",
        change_set_name="create-terraform-account-1",
        template_body="cloudformation_template",
        parameters={"BucketName": "terraform-account-1"},
        tags={"env": "test"},
    )
    merge_request_manager.create_merge_request.assert_called_once_with(
        data=MrData(
            account="account-1",
            content="terraform-account-1",
            path="data/templating/collections/terraform-init/account-1.yml",
        )
    )


def test_terraform_init_integration_reconcile_account_with_new_account_dry_run(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "account-1")
    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=True,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.create_stack.assert_not_called()
    merge_request_manager.create_merge_request.assert_called_once_with(
        data=MrData(
            account="account-1",
            content="terraform-account-1",
            path="data/templating/collections/terraform-init/account-1.yml",
        )
    )


def test_terraform_init_integration_reconcile_account_when_import_stack(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = None

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.create_stack.assert_called_once_with(
        stack_name="existing-bucket",
        change_set_name="import-existing-bucket",
        template_body="cloudformation_import_template",
        parameters={"BucketName": "existing-bucket"},
        tags={
            "account_key": "account_value",
            "common_key": "final_common_value",
            "env": "test",
            "payer_key": "payer_value",
        },
    )
    aws_api.cloudformation.update_stack.assert_called_once_with(
        stack_name="existing-bucket",
        template_body="cloudformation_template",
        parameters={"BucketName": "existing-bucket"},
        tags={
            "account_key": "account_value",
            "common_key": "final_common_value",
            "env": "test",
            "payer_key": "payer_value",
        },
    )
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_import_stack_dry_run(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = None

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=True,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.create_stack.assert_not_called()
    aws_api.cloudformation.update_stack.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_tags_mismatch(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = {
        "StackName": "terraform-terraform-state-already-set",
        "Tags": [
            {"Key": "account_key", "Value": "account_value"},
            {"Key": "common_key", "Value": "final_common_value"},
            {"Key": "env", "Value": "test-old"},
            {"Key": "payer_key", "Value": "payer_value"},
        ],
    }

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.update_stack.assert_called_once_with(
        stack_name="existing-bucket",
        template_body="cloudformation_template",
        parameters={"BucketName": "existing-bucket"},
        tags={
            "account_key": "account_value",
            "common_key": "final_common_value",
            "env": "test",
            "payer_key": "payer_value",
        },
    )
    aws_api.cloudformation.create_stack.assert_not_called()
    aws_api.cloudformation.get_template.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_tags_mismatch_dry_run(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = {
        "StackName": "terraform-terraform-state-already-set",
        "Tags": [
            {"Key": "account_key", "Value": "account_value"},
            {"Key": "common_key", "Value": "final_common_value"},
            {"Key": "env", "Value": "test-old"},
            {"Key": "payer_key", "Value": "payer_value"},
        ],
    }

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=True,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.update_stack.assert_not_called()
    aws_api.cloudformation.create_stack.assert_not_called()
    aws_api.cloudformation.get_template.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_template_body_mismatch(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = {
        "StackName": "terraform-terraform-state-already-set",
        "Tags": [
            {"Key": "account_key", "Value": "account_value"},
            {"Key": "common_key", "Value": "final_common_value"},
            {"Key": "env", "Value": "test"},
            {"Key": "payer_key", "Value": "payer_value"},
        ],
    }
    aws_api.cloudformation.get_template_body.return_value = "old_template_body"

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.get_template_body.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.update_stack.assert_called_once_with(
        stack_name="existing-bucket",
        template_body="cloudformation_template",
        parameters={"BucketName": "existing-bucket"},
        tags={
            "account_key": "account_value",
            "common_key": "final_common_value",
            "env": "test",
            "payer_key": "payer_value",
        },
    )
    aws_api.cloudformation.create_stack.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_template_body_mismatch_dry_run(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = {
        "StackName": "terraform-terraform-state-already-set",
        "Tags": [
            {"Key": "account_key", "Value": "account_value"},
            {"Key": "env", "Value": "test"},
            {"Key": "common_key", "Value": "final_common_value"},
            {"Key": "payer_key", "Value": "payer_value"},
        ],
    }
    aws_api.cloudformation.get_template_body.return_value = "old_template_body"

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=True,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.get_template_body.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.update_stack.assert_not_called()
    aws_api.cloudformation.create_stack.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()


def test_terraform_init_integration_reconcile_account_when_no_changes(
    aws_api: MagicMock,
    merge_request_manager: MagicMock,
    intg: TerraformInitIntegration,
    aws_accounts: list[AWSAccountV1],
) -> None:
    account = next(a for a in aws_accounts if a.name == "terraform-state-already-set")
    aws_api.cloudformation.get_stack.return_value = {
        "StackName": "terraform-terraform-state-already-set",
        "Tags": [
            {"Key": "account_key", "Value": "account_value"},
            {"Key": "common_key", "Value": "final_common_value"},
            {"Key": "env", "Value": "test"},
            {"Key": "payer_key", "Value": "payer_value"},
        ],
    }
    aws_api.cloudformation.get_template_body.return_value = "cloudformation_template"

    intg.reconcile_account(
        aws_api=aws_api,
        merge_request_manager=merge_request_manager,
        dry_run=False,
        account=account,
        state_template="{{bucket_name}}",
        cloudformation_template="cloudformation_template",
        cloudformation_import_template="cloudformation_import_template",
        default_tags={"env": "test"},
    )

    aws_api.cloudformation.get_stack.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.get_template_body.assert_called_once_with(
        stack_name="existing-bucket"
    )
    aws_api.cloudformation.create_stack.assert_not_called()
    aws_api.cloudformation.update_stack.assert_not_called()
    merge_request_manager.create_merge_request.assert_not_called()
