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

T = TypeVar("T", bound="SlackUsergroupActionUpdateUsers")


@_attrs_define
class SlackUsergroupActionUpdateUsers:
    """Action: Update usergroup users.

    Attributes:
        usergroup (str): Usergroup handle/name
        users (list[str]): List of users after update
        users_to_add (list[str]): List of users to add
        users_to_remove (list[str]): List of users to remove
        workspace (str): Workspace name
        action_type (Literal['update_users'] | Unset):  Default: 'update_users'.
    """

    usergroup: str
    users: list[str]
    users_to_add: list[str]
    users_to_remove: list[str]
    workspace: str
    action_type: Literal["update_users"] | Unset = "update_users"
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        usergroup = self.usergroup

        users = self.users

        users_to_add = self.users_to_add

        users_to_remove = self.users_to_remove

        workspace = self.workspace

        action_type = self.action_type

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "usergroup": usergroup,
            "users": users,
            "users_to_add": users_to_add,
            "users_to_remove": users_to_remove,
            "workspace": workspace,
        })
        if action_type is not UNSET:
            field_dict["action_type"] = action_type

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        d = dict(src_dict)
        usergroup = d.pop("usergroup")

        users = cast(list[str], d.pop("users"))

        users_to_add = cast(list[str], d.pop("users_to_add"))

        users_to_remove = cast(list[str], d.pop("users_to_remove"))

        workspace = d.pop("workspace")

        action_type = cast(Literal["update_users"] | Unset, d.pop("action_type", UNSET))
        if action_type != "update_users" and not isinstance(action_type, Unset):
            raise ValueError(
                f"action_type must match const 'update_users', got '{action_type}'"
            )

        slack_usergroup_action_update_users = cls(
            usergroup=usergroup,
            users=users,
            users_to_add=users_to_add,
            users_to_remove=users_to_remove,
            workspace=workspace,
            action_type=action_type,
        )

        slack_usergroup_action_update_users.additional_properties = d
        return slack_usergroup_action_update_users

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
