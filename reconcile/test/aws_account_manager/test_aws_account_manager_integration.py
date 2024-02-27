from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from reconcile.aws_account_manager.integration import AwsAccountMgmtIntegration
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountRequestV1,
    AWSAccountV1,
)
from reconcile.gql_definitions.fragments.aws_account_managed import (
    AWSAccountManaged,
    AWSQuotaV1,
)
from reconcile.utils.aws_api_typed.iam import AWSAccessKey


def test_aws_account_manager_utils_integration_early_exit(
    query_func: Callable, intg: AwsAccountMgmtIntegration
) -> None:
    early_exit_state = intg.get_early_exit_desired_state(query_func)
    assert "payer_accounts" in early_exit_state
    assert "non_organization_accounts" in early_exit_state


def test_aws_account_manager_utils_integration_render_account_tmpl_files(
    intg: AwsAccountMgmtIntegration, account_request: AWSAccountRequestV1
) -> None:
    tmpl = """
    # test access variables
    {{ accountRequest.name }}
    {{ uid }}
    {{ settings.whatever }}
    """
    output = intg.render_account_tmpl_file(
        template=tmpl,
        account_request=account_request,
        uid="123456",
        settings={"whatever": "whatever"},
    )
    assert (
        output
        == f"""
    # test access variables
    {account_request.name}
    123456
    whatever
    """
    )


def test_aws_account_manager_utils_integration_get_aws_accounts(
    query_func: Callable, intg: AwsAccountMgmtIntegration
) -> None:
    payer_accounts, non_org_accounts = intg.get_aws_accounts(query_func)
    assert len(payer_accounts) == 1
    assert payer_accounts[0].name == "starfleet"
    assert len(non_org_accounts) == 2
    assert non_org_accounts[0].name == "q"
    # payer accounts are also non-org accounts and are managed like any other non-org account!
    assert non_org_accounts[1].name == "starfleet"


def test_aws_account_manager_utils_integration_save_access_key(
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.save_access_key(
        "account", AWSAccessKey(AccessKeyId="access_key", SecretAccessKey="secret_key")
    )
    intg.secret_reader.vault_client.write.assert_called_once_with(  # type: ignore
        secret={
            "data": {
                "aws_access_key_id": "access_key",
                "aws_secret_access_key": "secret_key",
            },
            "path": "app-sre/creds/terraform/account/config",
        },
        decode_base64=False,
    )


def test_aws_account_manager_utils_integration_create_accounts(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    account_request: AWSAccountRequestV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    reconciler.create_organization_account.return_value = None
    intg.create_accounts(
        aws_api,
        reconciler,
        merge_request_manager,
        "account-template",
        [account_request],
    )
    reconciler.create_organization_account.assert_called_once_with(
        aws_api=aws_api,
        name=account_request.name,
        email=account_request.account_owner.email,
    )
    merge_request_manager.create_account_file.assert_not_called()


def test_aws_account_manager_utils_integration_create_accounts_create_account_file(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    account_request: AWSAccountRequestV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    reconciler.create_organization_account.return_value = "1111111111"
    intg.create_accounts(
        aws_api,
        reconciler,
        merge_request_manager,
        "account-template - {{ uid }}",
        [account_request],
    )
    reconciler.create_organization_account.assert_called_once_with(
        aws_api=aws_api,
        name=account_request.name,
        email=account_request.account_owner.email,
    )
    merge_request_manager.create_account_file.assert_called_once_with(
        account_request_file_path="/aws/data/request.yml",
        account_tmpl_file_content="account-template - 1111111111",
        account_tmpl_file_path="data/templating/collections/aws-account/data.yml",
    )


def test_aws_account_manager_utils_integration_reconcile_organization_accounts(
    aws_api: MagicMock,
    reconciler: MagicMock,
    org_account: AWSAccountManaged,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.reconcile_account = MagicMock()  # type: ignore
    intg.reconcile_organization_accounts(aws_api, reconciler, [org_account])
    reconciler.reconcile_organization_account.assert_called_once_with(
        aws_api=aws_api,
        default_tags={},
        enterprise_support=False,
        name="jeanluc",
        ou="/Root/alpha quadrant/uss enterprise/ncc-1701-d",
        tags={"ship": "USS Enterprise"},
        uid="111111111111",
    )
    intg.reconcile_account.assert_called_once()


def test_aws_account_manager_utils_integration_reconcile_account(
    aws_api: MagicMock,
    reconciler: MagicMock,
    non_org_account: AWSAccountV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.save_access_key = MagicMock()  # type: ignore
    reconciler.reconcile_account.return_value = "access_key"
    intg.reconcile_account(aws_api, reconciler, non_org_account)
    reconciler.reconcile_account.assert_called_once_with(
        aws_api=aws_api,
        alias=None,
        initial_user_name="terraform",
        initial_user_policy_arn="arn:aws:iam::aws:policy/AdministratorAccess",
        name="q",
        quotas=[
            AWSQuotaV1(serviceCode="ec2", quotaCode="L-1216C47A", value=64.0),
            AWSQuotaV1(serviceCode="eks", quotaCode="L-1194D53C", value=102.0),
        ],
    )
    intg.save_access_key.assert_called_once_with(non_org_account.name, "access_key")


def test_aws_account_manager_utils_integration_reconcile_account_already_done(
    aws_api: MagicMock,
    reconciler: MagicMock,
    non_org_account: AWSAccountV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.save_access_key = MagicMock()  # type: ignore
    reconciler.reconcile_account.return_value = None
    intg.reconcile_account(aws_api, reconciler, non_org_account)
    intg.save_access_key.assert_not_called()


def test_aws_account_manager_utils_integration_reconcile_payer_accounts(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    payer_accounts: list[AWSAccountV1],
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.create_accounts = MagicMock()  # type: ignore
    intg.reconcile_organization_accounts = MagicMock()  # type: ignore
    intg.reconcile_payer_accounts(
        reconciler,
        merge_request_manager,
        "/default-state-path/foo",
        "account-template",
        payer_accounts,
    )
    assert reconciler.state.state_path == "/default-state-path/foo/starfleet"
    intg.create_accounts.assert_called_once()
    intg.reconcile_organization_accounts.assert_called_once()


def test_aws_account_manager_utils_integration_reconcile_payer_accounts_missing_automation_role(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    payer_account: AWSAccountV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    payer_account.automation_role = None
    with pytest.raises(ValueError):
        intg.reconcile_payer_accounts(
            reconciler,
            merge_request_manager,
            "/default-state-path/foo",
            "account-template",
            [payer_account],
        )


def test_aws_account_manager_utils_integration_reconcile_non_organization_accounts(
    aws_api: MagicMock,
    reconciler: MagicMock,
    non_org_account: AWSAccountV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.reconcile_account = MagicMock()  # type: ignore
    intg.reconcile_non_organization_accounts(
        reconciler,
        "/default-state-path/foo",
        [non_org_account],
    )
    assert reconciler.state.state_path == "/default-state-path/foo/q"
    intg.reconcile_account.assert_called_once()
