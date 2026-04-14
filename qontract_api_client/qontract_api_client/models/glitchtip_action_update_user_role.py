from __future__ import annotations

from collections.abc import Mapping
from typing import (
    Any,
    Literal,
    TypeVar,
    cast,
)

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="GlitchtipActionUpdateUserRole")


@_attrs_define
class GlitchtipActionUpdateUserRole:
    """Action: Update a user's role in an organization.

    Attributes:
        email (str): User email
        instance (str): Glitchtip instance name
        organization (str): Organization name
        pk (int): User primary key (resolved at planning time)
        role (str): New role
        action_type (Literal['update_user_role'] | Unset):  Default: 'update_user_role'.
    """

    email: str
    instance: str
    organization: str
    pk: int
    role: str
    action_type: Literal["update_user_role"] | Unset = "update_user_role"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        instance = self.instance

        organization = self.organization

        pk = self.pk

        role = self.role

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "email": email,
            "instance": instance,
            "organization": organization,
            "pk": pk,
            "role": role,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        email = d.pop("email")

        instance = d.pop("instance")

        organization = d.pop("organization")

        pk = d.pop("pk")

        role = d.pop("role")

        action_type = cast(
            Literal["update_user_role"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "update_user_role" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_user_role', got '{action_type}'"
            )

        glitchtip_action_update_user_role = cls(
            email=email,
            instance=instance,
            organization=organization,
            pk=pk,
            role=role,
            action_type=action_type,
        )

        glitchtip_action_update_user_role.additional_properties = d
        return glitchtip_action_update_user_role

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
