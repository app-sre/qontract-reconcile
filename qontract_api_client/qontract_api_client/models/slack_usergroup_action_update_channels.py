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

T = TypeVar("T", bound="SlackUsergroupActionUpdateChannels")


@_attrs_define
class SlackUsergroupActionUpdateChannels:
    """Action: Update usergroup channels.

    Attributes:
        workspace (str): Slack workspace name
        usergroup (str): Usergroup handle/name
        action_type (Literal['update_channels'] | Unset):  Default: 'update_channels'.
        channels_to_add (list[str] | Unset): Channels to add to usergroup
        channels_to_remove (list[str] | Unset): Channels to remove from usergroup
    """

    workspace: str
    usergroup: str
    action_type: Literal["update_channels"] | Unset = "update_channels"
    channels_to_add: list[str] | Unset = UNSET
    channels_to_remove: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        workspace = self.workspace

        usergroup = self.usergroup

        action_type = self.action_type

        channels_to_add: list[str] | Unset = UNSET
        if not isinstance(self.channels_to_add, Unset):
            channels_to_add = self.channels_to_add

        channels_to_remove: list[str] | Unset = UNSET
        if not isinstance(self.channels_to_remove, Unset):
            channels_to_remove = self.channels_to_remove

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "workspace": workspace,
            "usergroup": usergroup,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type
        if channels_to_add is not UNSET:
            field_dict["channels_to_add"] = channels_to_add
        if channels_to_remove is not UNSET:
            field_dict["channels_to_remove"] = channels_to_remove

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        workspace = d.pop("workspace")

        usergroup = d.pop("usergroup")

        action_type = cast(
            "Literal['update_channels'] | Unset", d.pop("action_type", UNSET)
        )
        if action_type != "update_channels" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_channels', got '{action_type}'"
            )

        channels_to_add = cast("list[str]", d.pop("channels_to_add", UNSET))

        channels_to_remove = cast("list[str]", d.pop("channels_to_remove", UNSET))

        slack_usergroup_action_update_channels = cls(
            workspace=workspace,
            usergroup=usergroup,
            action_type=action_type,
            channels_to_add=channels_to_add,
            channels_to_remove=channels_to_remove,
        )

        slack_usergroup_action_update_channels.additional_properties = d
        return slack_usergroup_action_update_channels

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
