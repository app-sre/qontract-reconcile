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

T = TypeVar("T", bound="SlackUsergroupActionUpdateMetadata")


@_attrs_define
class SlackUsergroupActionUpdateMetadata:
    """Action: Update usergroup channels.

    Attributes:
        channels (list[str]): Usergroup channels
        description (str): Usergroup description
        usergroup (str): Usergroup handle/name
        workspace (str): Workspace name
        action_type (Literal['update_metadata'] | Unset):  Default: 'update_metadata'.
    """

    channels: list[str]
    description: str
    usergroup: str
    workspace: str
    action_type: Literal["update_metadata"] | Unset = "update_metadata"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        channels = self.channels

        description = self.description

        usergroup = self.usergroup

        workspace = self.workspace

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "channels": channels,
            "description": description,
            "usergroup": usergroup,
            "workspace": workspace,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        channels = cast(list[str], d.pop("channels"))

        description = d.pop("description")

        usergroup = d.pop("usergroup")

        workspace = d.pop("workspace")

        action_type = cast(
            Literal["update_metadata"] | Unset, d.pop("action_type", UNSET)
        )
        if action_type != "update_metadata" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_metadata', got '{action_type}'"
            )

        slack_usergroup_action_update_metadata = cls(
            channels=channels,
            description=description,
            usergroup=usergroup,
            workspace=workspace,
            action_type=action_type,
        )

        slack_usergroup_action_update_metadata.additional_properties = d
        return slack_usergroup_action_update_metadata

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
