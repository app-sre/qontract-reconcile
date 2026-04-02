from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.aws_payer_account_organization_account_tags import (
        AWSPayerAccountOrganizationAccountTags,
    )
    from ..models.secret import Secret


T = TypeVar("T", bound="AWSPayerAccount")


@_attrs_define
class AWSPayerAccount:
    """A payer (management) account in an AWS organization.

    Attributes:
        automation_role (str): IAM role ARN for account management
        automation_token (Secret): Reference to a secret stored in a secret manager.
        name (str): Account name
        resources_default_region (str): Default AWS region for API calls
        uid (str): AWS account ID
        organization_account_tags (AWSPayerAccountOrganizationAccountTags | Unset): Default tags for organization
            accounts
    """

    automation_role: str
    automation_token: Secret
    name: str
    resources_default_region: str
    uid: str
    organization_account_tags: AWSPayerAccountOrganizationAccountTags | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        automation_role = self.automation_role

        automation_token = self.automation_token.to_dict()

        name = self.name

        resources_default_region = self.resources_default_region

        uid = self.uid

        organization_account_tags: dict[str, Any] | Unset = UNSET
        if not isinstance(self.organization_account_tags, Unset):
            organization_account_tags = self.organization_account_tags.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "automation_role": automation_role,
            "automation_token": automation_token,
            "name": name,
            "resources_default_region": resources_default_region,
            "uid": uid,
        })
        if organization_account_tags is not UNSET:
            field_dict["organization_account_tags"] = organization_account_tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aws_payer_account_organization_account_tags import (
            AWSPayerAccountOrganizationAccountTags,
        )
        from ..models.secret import Secret

        d = dict(src_dict)
        automation_role = d.pop("automation_role")

        automation_token = Secret.from_dict(d.pop("automation_token"))

        name = d.pop("name")

        resources_default_region = d.pop("resources_default_region")

        uid = d.pop("uid")

        _organization_account_tags = d.pop("organization_account_tags", UNSET)
        organization_account_tags: AWSPayerAccountOrganizationAccountTags | Unset
        if isinstance(_organization_account_tags, Unset):
            organization_account_tags = UNSET
        else:
            organization_account_tags = (
                AWSPayerAccountOrganizationAccountTags.from_dict(
                    _organization_account_tags
                )
            )

        aws_payer_account = cls(
            automation_role=automation_role,
            automation_token=automation_token,
            name=name,
            resources_default_region=resources_default_region,
            uid=uid,
            organization_account_tags=organization_account_tags,
        )

        aws_payer_account.additional_properties = d
        return aws_payer_account

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
