from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

T = TypeVar("T", bound="SlackUsergroupConfig")


@_attrs_define
class SlackUsergroupConfig:
    """Desired state configuration for a single Slack usergroup.

    Attributes:
        description (str | Unset): Usergroup description Default: ''.
        users (list[str] | Unset): List of user emails (e.g., user@example.com)
        channels (list[str] | Unset): List of channel names (e.g., #general, team-channel)
    """

    description: str | Unset = ""
    users: list[str] | Unset = UNSET
    channels: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        description = self.description

        users: list[str] | Unset = UNSET
        if not isinstance(self.users, Unset):
            users = self.users

        channels: list[str] | Unset = UNSET
        if not isinstance(self.channels, Unset):
            channels = self.channels

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({})
        if description is not UNSET:
            field_dict["description"] = description
        if users is not UNSET:
            field_dict["users"] = users
        if channels is not UNSET:
            field_dict["channels"] = channels

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        description = d.pop("description", UNSET)

        users = cast(list[str], d.pop("users", UNSET))

        channels = cast(list[str], d.pop("channels", UNSET))

        slack_usergroup_config = cls(
            description=description,
            users=users,
            channels=channels,
        )

        slack_usergroup_config.additional_properties = d
        return slack_usergroup_config

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
