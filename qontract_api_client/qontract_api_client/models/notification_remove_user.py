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

T = TypeVar("T", bound="NotificationRemoveUser")


@_attrs_define
class NotificationRemoveUser:
    """Notify users when they are removed from the usergroup.

    Attributes:
        message (str): DM message to send to removed users
        action (Literal['remove-user'] | Unset):  Default: 'remove-user'.
    """

    message: str
    action: Literal["remove-user"] | Unset = "remove-user"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        message = self.message

        action = self.action

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "message": message,
        })
        if action is not UNSET:
            field_dict["action"] = action

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        message = d.pop("message")

        action = cast(Literal["remove-user"] | Unset, d.pop("action", UNSET))
        if action != "remove-user" and not isinstance(action, Unset):
            raise ValueError(f"action must match const 'remove-user', got '{action}'")

        notification_remove_user = cls(
            message=message,
            action=action,
        )

        notification_remove_user.additional_properties = d
        return notification_remove_user

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
