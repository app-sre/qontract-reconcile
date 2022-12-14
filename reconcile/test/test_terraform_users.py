import pytest

from reconcile.terraform_users import (
    send_email_invites,
    write_user_to_vault,
)


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
