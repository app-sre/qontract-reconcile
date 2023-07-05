from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

import reconcile.terraform_users as integ
from reconcile.gql_definitions.common.pgp_reencryption_settings import (
    PgpReencryptionSettingsQueryData,
)
from reconcile.terraform_users import (
    send_email_invites,
    write_user_to_vault,
)
from reconcile.utils.gql import GqlApi


@pytest.fixture
def new_users() -> list[tuple[str, str, str, str]]:
    return [
        (
            "aws1",
            "https://console.aws.amazon.com",
            "user1",
            "enc_password1",
        ),  # gitleaks:allow
    ]


def test_write_user_to_vault(mocker, new_users):
    vm = mocker.patch("reconcile.terraform_users._VaultClient", autospec=True)

    write_user_to_vault(vm, "test", new_users, [])

    vm.write.assert_called_once_with(
        {
            "path": "test/aws1_user1",
            "data": {
                "account": "aws1",
                "user_name": "user1",
                "console_url": "https://console.aws.amazon.com",
                "encrypted_password": "enc_password1",  # gitleaks:allow
            },
        },
        decode_base64=False,
    )


def test_write_user_to_vault_skipped(mocker, new_users):
    vm = mocker.patch("reconcile.terraform_users._VaultClient", autospec=True)

    write_user_to_vault(vm, "test", new_users, ["aws1"])

    vm.write.assert_not_called()


def test_send_email_invites(mocker, new_users):
    sm = mocker.patch("reconcile.terraform_users.SmtpClient", autospec=True)
    send_email_invites(new_users, sm, ["aws1"])
    sm.send_mails.assert_called_once()


def test_send_email_invites_skip(mocker, new_users):
    sm = mocker.patch("reconcile.terraform_users.SmtpClient", autospec=True)
    send_email_invites(new_users, sm, [])
    sm.send_mails.assert_not_called()


@pytest.fixture
def pgp_reencryption_settings(
    gql_class_factory: Callable[..., PgpReencryptionSettingsQueryData],
) -> PgpReencryptionSettingsQueryData:
    return gql_class_factory(
        PgpReencryptionSettingsQueryData,
        {
            "pgp_reencryption_settings": [],
        },
    )


@pytest.fixture
def test_aws_account_role() -> dict:
    return {
        "name": "test_aws_account",
        "users": [{"name": "test-user"}],
        "aws_groups": [
            {
                "name": "test-group",
                "account": {
                    "name": "test-account",
                },
            }
        ],
        "user_policies": [
            {
                "name": "test-policy",
                "account": {
                    "name": "test-account",
                },
            },
        ],
    }


@pytest.fixture
def test_aws_account() -> dict:
    return {
        "name": "test-account",
    }


def test_setup(
    mocker: MockerFixture,
    test_aws_account: dict,
    test_aws_account_role: dict,
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    mocked_gql_api = gql_api_builder({"roles": [test_aws_account_role]})
    mocker.patch("reconcile.terraform_users.gql").get_api.return_value = mocked_gql_api
    mocked_queries = mocker.patch("reconcile.terraform_users.queries")
    mocked_queries.get_aws_accounts.return_value = [test_aws_account]
    mocked_queries.get_app_interface_settings.return_value = None
    mocked_ts = mocker.patch("reconcile.terraform_users.Terrascript", autospec=True)
    mocked_aws = mocker.patch("reconcile.terraform_users.AWSApi", autospec=True)
    thread_pool_size = 1

    accounts, working_dirs, setup_err, aws_api = integ.setup(
        False, thread_pool_size, []
    )

    assert accounts == [test_aws_account]
    assert working_dirs == mocked_ts.return_value.dump.return_value
    assert setup_err == mocked_ts.return_value.populate_users.return_value
    assert aws_api == mocked_aws.return_value

    mocked_ts.assert_called_once_with(
        integ.QONTRACT_INTEGRATION,
        integ.QONTRACT_TF_PREFIX,
        thread_pool_size,
        [test_aws_account],
        settings=None,
    )
    mocked_ts.return_value.populate_users.assert_called_once_with(
        [test_aws_account_role],
        [],
        appsre_pgp_key=None,
    )
    mocked_aws.assert_called_once_with(
        1,
        [test_aws_account],
        settings=None,
        init_users=False,
    )


def test_empty_run(
    mocker: MockerFixture,
    pgp_reencryption_settings: PgpReencryptionSettingsQueryData,
    test_aws_account: dict,
    gql_api_builder: Callable[..., GqlApi],
) -> None:
    mocked_gql_api = gql_api_builder({"roles": []})
    mocker.patch("reconcile.terraform_users.gql").get_api.return_value = mocked_gql_api
    mocker.patch(
        "reconcile.terraform_users.query"
    ).return_value = pgp_reencryption_settings
    mocker.patch("reconcile.terraform_users.sys")
    mocked_queries = mocker.patch("reconcile.terraform_users.queries")
    mocked_queries.get_aws_accounts.return_value = [test_aws_account]
    mocked_queries.get_app_interface_settings.return_value = None
    mocker.patch("reconcile.terraform_users.Terrascript", autospec=True)
    mocker.patch("reconcile.terraform_users.AWSApi", autospec=True)
    mocked_logging = mocker.patch("reconcile.terraform_users.logging")

    integ.run(False, send_mails=False)

    mocked_logging.warning.assert_called_once_with(
        "No participating AWS accounts found, consider disabling this integration, account name: None"
    )
