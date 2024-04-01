from collections.abc import Iterable
from typing import Any, Protocol

from reconcile.utils.disabled_integrations import (
    HasDisableIntegrations,
    integration_is_enabled,
)
from reconcile.utils.secret_reader import SecretReader


class AccountNotFoundError(Exception):
    pass


Account = dict[str, Any]


def get_id_from_arn(arn):
    # arn:aws:iam::12345:<arntype>/id --> id
    return arn.split("/")[1]


def get_account_uid_from_arn(arn):
    # arn:aws:iam::12345:role/role-1 --> 12345
    return arn.split(":")[4]


def get_role_name_from_arn(arn: str) -> str:
    # arn:aws:iam::12345:role/role-1 --> role-1
    return arn.split("/")[-1]


def is_aws_managed_resource(arn: str) -> bool:
    # arn:aws:iam::aws:role/role-1 --> True
    # arn:aws:iam::12345:role/role-1 --> False
    return get_account_uid_from_arn(arn) == "aws"


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


class AccountSSO(HasDisableIntegrations, Protocol):
    name: str
    uid: str
    sso: bool | None


def unique_sso_aws_accounts(
    integration: str, accounts: Iterable[AccountSSO], account_name: str | None = None
) -> list[AccountSSO]:
    """Return a unique list of AWS accounts with SSO enabled."""
    filtered_account = {}
    for account in accounts:
        if account_name and account.name != account_name:
            continue
        if not account.sso:
            continue
        if not integration_is_enabled(integration, account):
            continue
        if account.uid in filtered_account:
            continue
        filtered_account[account.uid] = account
    return list(filtered_account.values())
