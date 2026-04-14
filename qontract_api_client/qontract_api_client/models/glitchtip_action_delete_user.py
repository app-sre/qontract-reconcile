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

T = TypeVar("T", bound="GlitchtipActionDeleteUser")


@_attrs_define
class GlitchtipActionDeleteUser:
    """Action: Remove a user from an organization.

    Attributes:
        email (str): User email
        instance (str): Glitchtip instance name
        organization (str): Organization name
        pk (int): User primary key (resolved at planning time)
        action_type (Literal['delete_user'] | Unset):  Default: 'delete_user'.
    """

    email: str
    instance: str
    organization: str
    pk: int
    action_type: Literal["delete_user"] | Unset = "delete_user"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        instance = self.instance

        organization = self.organization

        pk = self.pk

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "email": email,
            "instance": instance,
            "organization": organization,
            "pk": pk,
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

        action_type = cast(Literal["delete_user"] | Unset, d.pop("action_type", UNSET))
        if action_type != "delete_user" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'delete_user', got '{action_type}'"
            )

        glitchtip_action_delete_user = cls(
            email=email,
            instance=instance,
            organization=organization,
            pk=pk,
            action_type=action_type,
        )

        glitchtip_action_delete_user.additional_properties = d
        return glitchtip_action_delete_user

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
