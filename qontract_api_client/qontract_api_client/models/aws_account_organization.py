from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.aws_account_organization_tags import AWSAccountOrganizationTags


T = TypeVar("T", bound="AWSAccountOrganization")


@_attrs_define
class AWSAccountOrganization:
    """Organization membership details for an AWS account.

    Attributes:
        ou (str): Organizational Unit path
        tags (AWSAccountOrganizationTags | Unset): Tags to apply to the account
    """

    ou: str
    tags: AWSAccountOrganizationTags | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        ou = self.ou

        tags: dict[str, Any] | Unset = UNSET
        if not isinstance(self.tags, Unset):
            tags = self.tags.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "ou": ou,
        })
        if tags is not UNSET:
            field_dict["tags"] = tags

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.aws_account_organization_tags import AWSAccountOrganizationTags

        d = dict(src_dict)
        ou = d.pop("ou")

        _tags = d.pop("tags", UNSET)
        tags: AWSAccountOrganizationTags | Unset
        if isinstance(_tags, Unset):
            tags = UNSET
        else:
            tags = AWSAccountOrganizationTags.from_dict(_tags)

        aws_account_organization = cls(
            ou=ou,
            tags=tags,
        )

        aws_account_organization.additional_properties = d
        return aws_account_organization

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
