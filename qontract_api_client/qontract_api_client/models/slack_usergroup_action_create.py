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

T = TypeVar("T", bound="SlackUsergroupActionCreate")


@_attrs_define
class SlackUsergroupActionCreate:
    """Action: Create a new usergroup.

    Attributes:
        workspace (str): Workspace name
        usergroup (str): Usergroup handle/name
        users (list[str]): List of users to add
        description (str): Usergroup description
        action_type (Literal['create'] | Unset):  Default: 'create'.
    """

    workspace: str
    usergroup: str
    users: list[str]
    description: str
    action_type: Literal["create"] | Unset = "create"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        workspace = self.workspace

        usergroup = self.usergroup

        users = self.users

        description = self.description

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "workspace": workspace,
            "usergroup": usergroup,
            "users": users,
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

        users = cast(list[str], d.pop("users"))

        description = d.pop("description")

        action_type = cast(Literal["create"] | Unset, d.pop("action_type", UNSET))
        if action_type != "create" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'create', got '{action_type}'"
            )

        slack_usergroup_action_create = cls(
            workspace=workspace,
            usergroup=usergroup,
            users=users,
            description=description,
            action_type=action_type,
        )

        slack_usergroup_action_create.additional_properties = d
        return slack_usergroup_action_create

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
