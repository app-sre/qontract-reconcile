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

T = TypeVar("T", bound="GlitchtipActionInviteUser")


@_attrs_define
class GlitchtipActionInviteUser:
    """Action: Invite a user to an organization.

    Attributes:
        email (str): User email
        instance (str): Glitchtip instance name
        organization (str): Organization name
        role (str): Organization role
        action_type (Literal['invite_user'] | Unset):  Default: 'invite_user'.
    """

    email: str
    instance: str
    organization: str
    role: str
    action_type: Literal["invite_user"] | Unset = "invite_user"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        email = self.email

        instance = self.instance

        organization = self.organization

        role = self.role

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "email": email,
            "instance": instance,
            "organization": organization,
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

        role = d.pop("role")

        action_type = cast(Literal["invite_user"] | Unset, d.pop("action_type", UNSET))
        if action_type != "invite_user" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'invite_user', got '{action_type}'"
            )

        glitchtip_action_invite_user = cls(
            email=email,
            instance=instance,
            organization=organization,
            role=role,
            action_type=action_type,
        )

        glitchtip_action_invite_user.additional_properties = d
        return glitchtip_action_invite_user

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
