from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.aws_account_manager_create_account_request_default_tags import (
        AWSAccountManagerCreateAccountRequestDefaultTags,
    )
    from ..models.aws_account_request import AWSAccountRequest
    from ..models.aws_payer_account import AWSPayerAccount


T = TypeVar("T", bound="AWSAccountManagerCreateAccountRequest")


@_attrs_define
class AWSAccountManagerCreateAccountRequest:
    """Request to create a plain AWS account.

    Handles only AWS-level operations: create org account, describe,
    tag, set alias. One payer account + one account request per call.

        Attributes:
            account_request (AWSAccountRequest): Request to create a new AWS account under a payer account.
            payer_account (AWSPayerAccount): A payer (management) account in an AWS organization.
            default_tags (AWSAccountManagerCreateAccountRequestDefaultTags | Unset): Default tags for the new account
            dry_run (bool | Unset): If True, only calculate actions without executing. Default: True.
            organization_account_role (str | Unset): Role to assume in the new account Default:
                'OrganizationAccountAccessRole'.
    """

    account_request: AWSAccountRequest
    payer_account: AWSPayerAccount
    default_tags: AWSAccountManagerCreateAccountRequestDefaultTags | Unset = UNSET
    dry_run: bool | Unset = True
    organization_account_role: str | Unset = "OrganizationAccountAccessRole"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        account_request = self.account_request.to_dict()

        payer_account = self.payer_account.to_dict()

        default_tags: dict[str, Any] | Unset = UNSET
        if not isinstance(self.default_tags, Unset):
            default_tags = self.default_tags.to_dict()

        dry_run = self.dry_run

        organization_account_role = self.organization_account_role

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "account_request": account_request,
            "payer_account": payer_account,
        })
        if default_tags is not UNSET:
            field_dict["default_tags"] = default_tags
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run
        if organization_account_role is not UNSET:
            field_dict["organization_account_role"] = organization_account_role

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aws_account_manager_create_account_request_default_tags import (
            AWSAccountManagerCreateAccountRequestDefaultTags,
        )
        from ..models.aws_account_request import AWSAccountRequest
        from ..models.aws_payer_account import AWSPayerAccount

        d = dict(src_dict)
        account_request = AWSAccountRequest.from_dict(d.pop("account_request"))

        payer_account = AWSPayerAccount.from_dict(d.pop("payer_account"))

        _default_tags = d.pop("default_tags", UNSET)
        default_tags: AWSAccountManagerCreateAccountRequestDefaultTags | Unset
        if isinstance(_default_tags, Unset):
            default_tags = UNSET
        else:
            default_tags = AWSAccountManagerCreateAccountRequestDefaultTags.from_dict(
                _default_tags
            )

        dry_run = d.pop("dry_run", UNSET)

        organization_account_role = d.pop("organization_account_role", UNSET)

        aws_account_manager_create_account_request = cls(
            account_request=account_request,
            payer_account=payer_account,
            default_tags=default_tags,
            dry_run=dry_run,
            organization_account_role=organization_account_role,
        )

        aws_account_manager_create_account_request.additional_properties = d
        return aws_account_manager_create_account_request

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
