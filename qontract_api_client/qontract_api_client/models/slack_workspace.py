from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.secret import Secret
    from ..models.slack_usergroup import SlackUsergroup


T = TypeVar("T", bound="SlackWorkspace")


@_attrs_define
class SlackWorkspace:
    """A Slack workspace with its token and usergroups.

    Attributes:
        name (str): Workspace name (unique identifier)
        usergroups (list[SlackUsergroup]): List of usergroups in this workspace
        managed_usergroups (list[str]): This list shows the usergroup handles/names managed by qontract-api. Any user
            group not included here will be abandoned during reconciliation.
        token (Secret): Reference to a secret stored in a secret manager.
    """

    name: str
    usergroups: list[SlackUsergroup]
    managed_usergroups: list[str]
    token: Secret
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        name = self.name

        usergroups = []
        for usergroups_item_data in self.usergroups:
            usergroups_item = usergroups_item_data.to_dict()
            usergroups.append(usergroups_item)

        managed_usergroups = self.managed_usergroups

        token = self.token.to_dict()

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "name": name,
            "usergroups": usergroups,
            "managed_usergroups": managed_usergroups,
            "token": token,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.secret import Secret
        from ..models.slack_usergroup import SlackUsergroup

        d = dict(src_dict)
        name = d.pop("name")

        usergroups = []
        _usergroups = d.pop("usergroups")
        for usergroups_item_data in _usergroups:
            usergroups_item = SlackUsergroup.from_dict(usergroups_item_data)

            usergroups.append(usergroups_item)

        managed_usergroups = cast(list[str], d.pop("managed_usergroups"))

        token = Secret.from_dict(d.pop("token"))

        slack_workspace = cls(
            name=name,
            usergroups=usergroups,
            managed_usergroups=managed_usergroups,
            token=token,
        )

        slack_workspace.additional_properties = d
        return slack_workspace

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
