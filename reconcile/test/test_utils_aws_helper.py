import pytest
import reconcile.utils.aws_helper as awsh
from reconcile.utils.secret_reader import SecretReader


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


def test_get_tf_secrets(mocker):
    account_name = "a"
    automation_token = "at"
    account = {"name": account_name, "automationToken": automation_token}
    mocker.patch(
        "reconcile.utils.secret_reader.SecretReader.read_all",
        return_value=automation_token,
    )
    secret_reader = SecretReader()
    result = awsh.get_tf_secrets(account, secret_reader)
    assert result == (account_name, automation_token)


def test_get_account_found():
    account_name = "a'"
    acc_a = {"name": account_name}
    accounts = [
        acc_a,
        {"name": "b"},
    ]
    result = awsh.get_account(accounts, account_name)
    assert result == acc_a


def test_get_account_not_found():
    with pytest.raises(awsh.AccountNotFoundError):
        awsh.get_account([], "a")


@pytest.mark.parametrize(
    "az,region",
    [
        ("us-east-1c", "us-east-1"),
        ("eu-central-1a", "eu-central-1"),
        ("us-west-2b", "us-west-2"),
    ],
)
def test_get_region_from_availability_zone(az, region):
    assert awsh.get_region_from_availability_zone(az) == region
