from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.ldap_group_member import LdapGroupMember


T = TypeVar("T", bound="LdapGroupMembersResponse")


@_attrs_define
class LdapGroupMembersResponse:
    """Response model for LDAP group members endpoint.

    Attributes:
        members: List of LDAP group members

        Attributes:
            members (list[LdapGroupMember] | Unset): List of LDAP group members
    """

    members: list[LdapGroupMember] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        members: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.members, Unset):
            members = []
            for members_item_data in self.members:
                members_item = members_item_data.to_dict()
                members.append(members_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if members is not UNSET:
            field_dict["members"] = members

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.ldap_group_member import LdapGroupMember

        d = dict(src_dict)
        _members = d.pop("members", UNSET)
        members: list[LdapGroupMember] | Unset = UNSET
        if _members is not UNSET:
            members = []
            for members_item_data in _members:
                members_item = LdapGroupMember.from_dict(members_item_data)

                members.append(members_item)

        ldap_group_members_response = cls(
            members=members,
        )

        ldap_group_members_response.additional_properties = d
        return ldap_group_members_response

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
