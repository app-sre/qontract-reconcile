import datetime
from collections.abc import Callable, Mapping
from textwrap import dedent
from typing import Any
from unittest.mock import ANY, MagicMock

import pytest
from pytest_mock import MockerFixture

from reconcile.aws_account_manager import integration
from reconcile.aws_account_manager.integration import AwsAccountMgmtIntegration
from reconcile.gql_definitions.aws_account_manager.aws_accounts import (
    AWSAccountRequestV1,
    AWSAccountV1,
)
from reconcile.gql_definitions.fragments.aws_account_managed import (
    AWSAccountManaged,
    AWSContactV1,
    AWSQuotaV1,
)
from qontract_utils.aws_api_typed.iam import AWSAccessKey


def test_aws_account_manager_utils_integration_early_exit(
    query_func: Callable, intg: AwsAccountMgmtIntegration
) -> None:
    early_exit_state = intg.get_early_exit_desired_state(query_func)
    assert "payer_accounts" in early_exit_state
    assert "non_organization_accounts" in early_exit_state


def test_aws_account_manager_utils_integration_render_account_tmpl_files(
    mocker: MockerFixture,
    intg: AwsAccountMgmtIntegration,
    account_request: AWSAccountRequestV1,
) -> None:
    mocker.patch.object(
        integration,
        "utc_now",
        return_value=datetime.datetime(2024, 9, 30, 20, 15, 0, tzinfo=datetime.UTC),
    )
    tmpl = dedent("""
    # test access variables
    {{ accountRequest.name }}
    {{ uid }}
    {{ settings.whatever }}
        {{ timestamp }}
    """)
    output = intg.render_account_tmpl_file(
        template=tmpl,
        account_request=account_request,
        uid="123456",
        settings={"whatever": "whatever"},
    )
    assert output == dedent(f"""
    # test access variables
    {account_request.name}
    123456
    whatever
        1727727300
    """)


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


def test_aws_account_manager_utils_integration_get_aws_accounts_bad_email_in_account_request(
    intg: AwsAccountMgmtIntegration,
    data_factory: Callable[[type[AWSAccountV1], Mapping[str, Any]], Mapping[str, Any]],
) -> None:
    with pytest.raises(ValueError, match="Invalid email"):
        intg.get_aws_accounts(
            lambda *args, **kwargs: {
                "accounts": [
                    data_factory(
                        AWSAccountV1,
                        {
                            "name": "q",
                            "uid": "222222222222",
                            "premiumSupport": False,
                            "quotaLimits": [],
                            "resourcesDefaultRegion": "us-east-1",
                            "supportedDeploymentRegions": ["ca-east-1", "ca-west-2"],
                            "securityContact": {
                                "name": "security contact name",
                                "email": "security@example.com",
                                "phoneNumber": "+1234567890",
                            },
                            "automationToken": {"path": "vault-path", "field": "all"},
                            "accountOwners": [
                                {"email": "already-in-use-email@example.com"}
                            ],
                        },
                    ),
                    # payer account
                    data_factory(
                        AWSAccountV1,
                        {
                            "name": "starfleet",
                            "uid": "471112852898",
                            "premiumSupport": True,
                            "resourcesDefaultRegion": "us-east-1",
                            "securityContact": {
                                "name": "security contact name",
                                "email": "security@example.com",
                                "phoneNumber": "+1234567890",
                            },
                            "automationToken": {"path": "vault-path", "field": "all"},
                            "accountOwners": [{"email": "starfleet@example.com"}],
                            "automationRole": {
                                "awsAccountManager": "AwsAccountManager"
                            },
                            "account_requests": [
                                {
                                    "path": "/aws/data/request.yml",
                                    "name": "data",
                                    "description": "Request for a new AWS account for the United Federation of Planets",
                                    "accountOwner": {
                                        "name": "AppSRE",
                                        # duplicate email to trigger the error
                                        "email": "already-in-use-email@example.com",
                                    },
                                    "organization": {
                                        "ou": "/Root/alpha quadrant/uss enterprise/ncc-1701-d",
                                        "tags": '{"ship": "USS Enterprise"}',
                                        "payerAccount": {"path": "/aws/starfleet.yml"},
                                    },
                                    "quotaLimits": [
                                        {"path": "/aws/whatever/quota-limits.yml"}
                                    ],
                                },
                            ],
                            "organization_accounts": [],
                        },
                    ),
                ]
            }
        )


def test_aws_account_manager_utils_integration_get_aws_accounts_duplicate_email_across_payer_accounts(
    intg: AwsAccountMgmtIntegration,
    data_factory: Callable[[type[AWSAccountV1], Mapping[str, Any]], Mapping[str, Any]],
) -> None:
    with pytest.raises(ValueError, match="Invalid email"):
        intg.get_aws_accounts(
            lambda *args, **kwargs: {
                "accounts": [
                    # first payer account
                    data_factory(
                        AWSAccountV1,
                        {
                            "name": "starfleet",
                            "uid": "111111111111",
                            "premiumSupport": True,
                            "resourcesDefaultRegion": "us-east-1",
                            "securityContact": {
                                "name": "security contact name",
                                "email": "security@example.com",
                                "phoneNumber": "+1234567890",
                            },
                            "automationToken": {"path": "vault-path", "field": "all"},
                            "accountOwners": [{"email": "starfleet@example.com"}],
                            "automationRole": {
                                "awsAccountManager": "AwsAccountManager"
                            },
                            "account_requests": [
                                {
                                    "path": "/aws/data/request1.yml",
                                    "name": "data1",
                                    "description": "Request for a new AWS account",
                                    "accountOwner": {
                                        "name": "AppSRE",
                                        "email": "duplicate@example.com",
                                    },
                                    "organization": {
                                        "ou": "/Root/alpha quadrant/uss enterprise/ncc-1701-d",
                                        "tags": '{"ship": "USS Enterprise"}',
                                        "payerAccount": {"path": "/aws/starfleet.yml"},
                                    },
                                    "quotaLimits": [],
                                },
                            ],
                            "organization_accounts": [],
                        },
                    ),
                    # second payer account with duplicate email
                    data_factory(
                        AWSAccountV1,
                        {
                            "name": "klingon",
                            "uid": "222222222222",
                            "premiumSupport": True,
                            "resourcesDefaultRegion": "us-east-1",
                            "securityContact": {
                                "name": "security contact name",
                                "email": "security@example.com",
                                "phoneNumber": "+1234567890",
                            },
                            "automationToken": {"path": "vault-path", "field": "all"},
                            "accountOwners": [{"email": "klingon@example.com"}],
                            "automationRole": {
                                "awsAccountManager": "AwsAccountManager"
                            },
                            "account_requests": [
                                {
                                    "path": "/aws/data/request2.yml",
                                    "name": "data2",
                                    "description": "Request for another AWS account",
                                    "accountOwner": {
                                        "name": "AppSRE",
                                        # duplicate email - should trigger error
                                        "email": "duplicate@example.com",
                                    },
                                    "organization": {
                                        "ou": "/Root/beta quadrant/klingon/qo-nos",
                                        "tags": '{"empire": "Klingon"}',
                                        "payerAccount": {"path": "/aws/klingon.yml"},
                                    },
                                    "quotaLimits": [],
                                },
                            ],
                            "organization_accounts": [],
                        },
                    ),
                ]
            }
        )


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
            "path": "app-sre-v2/creds/terraform/account/config",
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
    reconciler.create_iam_user.assert_not_called()
    merge_request_manager.create_account_file.assert_not_called()


def test_aws_account_manager_utils_integration_create_accounts_save_access_key(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    account_request: AWSAccountRequestV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.save_access_key = MagicMock()  # type: ignore
    reconciler.create_organization_account.return_value = "1111111111"
    reconciler.create_iam_user.return_value = "access-key"
    intg.create_accounts(
        aws_api,
        reconciler,
        merge_request_manager,
        "account-template - {{ uid }}",
        [account_request],
    )
    aws_api.assume_role.assert_called_once_with(
        account_id="1111111111", role="OrganizationAccountAccessRole"
    )
    reconciler.create_organization_account.assert_called_once_with(
        aws_api=aws_api,
        name=account_request.name,
        email=account_request.account_owner.email,
    )
    merge_request_manager.create_account_file.assert_called_once_with(
        title=ANY,
        account_request_file_path="data/aws/data/request.yml",
        account_tmpl_file_content="account-template - 1111111111",
        account_tmpl_file_path="data/templating/collections/aws-account/data.yml",
    )
    intg.save_access_key.assert_called_once()


def test_aws_account_manager_utils_integration_create_accounts_create_account_file(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    account_request: AWSAccountRequestV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    reconciler.create_organization_account.return_value = "1111111111"
    reconciler.create_iam_user.return_value = None
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
        title=ANY,
        account_request_file_path="data/aws/data/request.yml",
        account_tmpl_file_content="account-template - 1111111111",
        account_tmpl_file_path="data/templating/collections/aws-account/data.yml",
    )


def test_aws_account_manager_utils_integration_create_accounts_takeover(
    aws_api: MagicMock,
    reconciler: MagicMock,
    merge_request_manager: MagicMock,
    account_request: AWSAccountRequestV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    reconciler.create_iam_user.return_value = None
    # if account_request.uid is set, we assume it's a takeover
    account_request.uid = "1111111111"
    intg.create_accounts(
        aws_api,
        reconciler,
        merge_request_manager,
        "account-template - {{ uid }}",
        [account_request],
    )
    reconciler.create_organization_account.assert_not_called()
    reconciler.create_iam_user.assert_called_once()
    merge_request_manager.create_account_file.assert_called_once()


def test_aws_account_manager_utils_integration_reconcile_organization_accounts(
    aws_api: MagicMock,
    reconciler: MagicMock,
    org_account: AWSAccountManaged,
    intg: AwsAccountMgmtIntegration,
) -> None:
    intg.reconcile_account = MagicMock()  # type: ignore
    intg.reconcile_organization_accounts(
        aws_api, reconciler, [org_account], default_tags={"ship": "USS Enterprise"}
    )
    reconciler.reconcile_organization_account.assert_called_once_with(
        aws_api=aws_api,
        enterprise_support=False,
        name="jeanluc",
        ou="/Root/alpha quadrant/uss enterprise/ncc-1701-d",
        tags={"ship": "USS Enterprise", "app-interface-name": "jeanluc"},
        uid="111111111111",
    )
    intg.reconcile_account.assert_called_once()


def test_aws_account_manager_utils_integration_reconcile_account(
    aws_api: MagicMock,
    reconciler: MagicMock,
    non_org_account: AWSAccountV1,
    intg: AwsAccountMgmtIntegration,
) -> None:
    reconciler.reconcile_account.return_value = "access_key"
    intg.reconcile_account(aws_api, reconciler, non_org_account)
    reconciler.reconcile_account.assert_called_once_with(
        aws_api=aws_api,
        alias=None,
        name="q",
        quotas=[
            AWSQuotaV1(serviceCode="ec2", quotaCode="L-1216C47A", value=64.0),
            AWSQuotaV1(serviceCode="eks", quotaCode="L-1194D53C", value=102.0),
        ],
        security_contact=AWSContactV1(
            name="security contact name",
            title=None,
            email="security@example.com",
            phoneNumber="+1234567890",
        ),
        regions=["ca-east-1", "ca-west-2"],
    )


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
