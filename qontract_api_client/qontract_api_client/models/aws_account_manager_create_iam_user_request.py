from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.aws_payer_account import AWSPayerAccount


T = TypeVar("T", bound="AWSAccountManagerCreateIAMUserRequest")


@_attrs_define
class AWSAccountManagerCreateIAMUserRequest:
    """Request to create an IAM user in an AWS account.

    Assumes into the account via the payer's manager role and creates
    an IAM user with the specified policy. Credentials are saved to Vault.

        Attributes:
            account_name (str): Name of the target account
            account_uid (str): AWS account ID of the target account
            payer_account (AWSPayerAccount): A payer (management) account in an AWS organization.
            policy_arn (str): Policy ARN to attach to the IAM user
            secret_vault_path (str): Vault path for storing IAM credentials
            user_name (str): Name of the IAM user to create
            dry_run (bool | Unset): If True, only calculate actions without executing. Default: True.
            organization_account_role (str | Unset): Role to assume in the target account Default:
                'OrganizationAccountAccessRole'.
    """

    account_name: str
    account_uid: str
    payer_account: AWSPayerAccount
    policy_arn: str
    secret_vault_path: str
    user_name: str
    dry_run: bool | Unset = True
    organization_account_role: str | Unset = "OrganizationAccountAccessRole"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_name = self.account_name

        account_uid = self.account_uid

        payer_account = self.payer_account.to_dict()

        policy_arn = self.policy_arn

        secret_vault_path = self.secret_vault_path

        user_name = self.user_name

        dry_run = self.dry_run

        organization_account_role = self.organization_account_role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_name": account_name,
            "account_uid": account_uid,
            "payer_account": payer_account,
            "policy_arn": policy_arn,
            "secret_vault_path": secret_vault_path,
            "user_name": user_name,
        })
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if organization_account_role is not UNSET:
            field_dict["organization_account_role"] = organization_account_role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aws_payer_account import AWSPayerAccount

        d = dict(src_dict)
        account_name = d.pop("account_name")

        account_uid = d.pop("account_uid")

        payer_account = AWSPayerAccount.from_dict(d.pop("payer_account"))

        policy_arn = d.pop("policy_arn")

        secret_vault_path = d.pop("secret_vault_path")

        user_name = d.pop("user_name")

        dry_run = d.pop("dry_run", UNSET)

        organization_account_role = d.pop("organization_account_role", UNSET)

        aws_account_manager_create_iam_user_request = cls(
            account_name=account_name,
            account_uid=account_uid,
            payer_account=payer_account,
            policy_arn=policy_arn,
            secret_vault_path=secret_vault_path,
            user_name=user_name,
            dry_run=dry_run,
            organization_account_role=organization_account_role,
        )

        aws_account_manager_create_iam_user_request.additional_properties = d
        return aws_account_manager_create_iam_user_request

    @property
    def additional_keys(self) -> list[str]:
        return list(self.additional_properties.keys())

    def __getitem__(self, key: str) -> Any:
        return self.additional_properties[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.additional_properties[key] = value

    def __delitem__(self, key: str) -> None:
        del self.additional_properties[key]

    def __contains__(self, key: str) -> bool:
        return key in self.additional_properties
