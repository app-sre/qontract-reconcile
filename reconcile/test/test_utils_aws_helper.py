import pytest
import reconcile.utils.aws_helper as awsh


def test_get_user_id_from_arn():
    user_id = "id"
    arn = f"arn:aws:iam::12345:user/{user_id}"
    result = awsh.get_user_id_from_arn(arn)
    assert result == user_id


def test_get_account_uid_from_arn():
    uid = "12345"
    arn = f"arn:aws:iam::{uid}:role/role-1"
    result = awsh.get_account_uid_from_arn(arn)
    assert result == uid


def test_get_details_from_role_link():
    role_link = "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    expected = ("12345", "role-1")
    result = awsh.get_details_from_role_link(role_link)
    assert result == expected


def test_get_role_arn_from_role_link():
    role_link = "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    expected = "arn:aws:iam::12345:role/role-1"
    result = awsh.get_role_arn_from_role_link(role_link)
    assert result == expected


def test_get_account_uid_from_role_link():
    role_link = "https://signin.aws.amazon.com/switchrole?account=12345&roleName=role-1"
    expected = "12345"
    result = awsh.get_account_uid_from_role_link(role_link)
    assert result == expected


class MockSecretReader:
    @staticmethod
    def read_all(token):
        return token


def test_get_tf_secrets():
    account = {"name": "a", "automationToken": "at"}
    secret_reader = MockSecretReader()
    result = awsh.get_tf_secrets(secret_reader, account)
    assert result == ("a", "at")


def test_get_account_found():
    acc_a = {"name": "a"}
    accounts = [
        acc_a,
        {"name": "b"},
    ]
    result = awsh.get_account(accounts, "a")
    assert result == acc_a


def test_get_account_not_found():
    accounts = []
    with pytest.raises(awsh.AccountNotFoundError):
        awsh.get_account(accounts, "a")
