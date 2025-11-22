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

T = TypeVar("T", bound="SlackUsergroupActionUpdateDescription")


@_attrs_define
class SlackUsergroupActionUpdateDescription:
    """Action: Update usergroup description.

    Attributes:
        workspace (str): Slack workspace name
        usergroup (str): Usergroup handle/name
        description (str): New description
        action_type (Literal['update_description'] | Unset):  Default: 'update_description'.
    """

    workspace: str
    usergroup: str
    description: str
    action_type: Literal["update_description"] | Unset = "update_description"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        workspace = self.workspace

        usergroup = self.usergroup

        description = self.description

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "workspace": workspace,
            "usergroup": usergroup,
            "description": description,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        workspace = d.pop("workspace")

        usergroup = d.pop("usergroup")

        description = d.pop("description")

        action_type = cast(
            "Literal['update_description'] | Unset", d.pop("action_type", UNSET)
        )
        if action_type != "update_description" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_description', got '{action_type}'"
            )

        slack_usergroup_action_update_description = cls(
            workspace=workspace,
            usergroup=usergroup,
            description=description,
            action_type=action_type,
        )

        slack_usergroup_action_update_description.additional_properties = d
        return slack_usergroup_action_update_description

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
