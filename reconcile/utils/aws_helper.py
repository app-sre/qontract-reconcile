from collections.abc import Iterable
from typing import Any

from reconcile.utils.secret_reader import SecretReader


class AccountNotFoundError(Exception):
    pass


Account = dict[str, Any]


def get_user_id_from_arn(arn):
    # arn:aws:iam::12345:user/id --> id
    return arn.split("/")[1]


def get_account_uid_from_arn(arn):
    # arn:aws:iam::12345:role/role-1 --> 12345
    return arn.split(":")[4]


def get_details_from_role_link(role_link):
    # https://signin.aws.amazon.com/switchrole?
    # account=<uid>&roleName=<role_name> -->
    # 12345, role-1
    details = role_link.split("?")[1].split("&")
    uid = details[0].split("=")[1]
    role_name = details[1].split("=")[1]
    return uid, role_name


def get_role_arn_from_role_link(role_link):
    # https://signin.aws.amazon.com/switchrole?
    # account=<uid>&roleName=<role_name> -->
    # arn:aws:iam::12345:role/role-1
    uid, role_name = get_details_from_role_link(role_link)
    return f"arn:aws:iam::{uid}:role/{role_name}"


def get_account_uid_from_role_link(role_link):
    uid, _ = get_details_from_role_link(role_link)
    return uid


def get_tf_secrets(account: Account, secret_reader: SecretReader) -> tuple[str, dict]:
    account_name = account["name"]
    automation_token = account["automationToken"]
    secret = secret_reader.read_all(automation_token)
    return (account_name, secret)


def get_account(accounts: Iterable[Account], account_name: str) -> Account:
    for a in accounts:
        if a["name"] == account_name:
            return a

    raise AccountNotFoundError(account_name)


def get_region_from_availability_zone(availability_zone: str) -> str:
    return availability_zone[:-1]
