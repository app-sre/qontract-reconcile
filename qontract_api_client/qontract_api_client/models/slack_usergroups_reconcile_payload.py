from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

if TYPE_CHECKING:
    from ..models.slack_usergroups_user import SlackUsergroupsUser
    from ..models.slack_workspace_request import SlackWorkspaceRequest


T = TypeVar("T", bound="SlackUsergroupsReconcilePayload")


@_attrs_define
class SlackUsergroupsReconcilePayload:
    """
    Attributes:
        workspaces (list[SlackWorkspaceRequest]): List of Slack workspaces with their usergroups
        users (list[SlackUsergroupsUser]):
    """

    workspaces: list[SlackWorkspaceRequest]
    users: list[SlackUsergroupsUser]
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        workspaces = []
        for workspaces_item_data in self.workspaces:
            workspaces_item = workspaces_item_data.to_dict()
            workspaces.append(workspaces_item)

        users = []
        for users_item_data in self.users:
            users_item = users_item_data.to_dict()
            users.append(users_item)

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "workspaces": workspaces,
            "users": users,
        })

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.slack_usergroups_user import SlackUsergroupsUser
        from ..models.slack_workspace_request import SlackWorkspaceRequest

        d = dict(src_dict)
        workspaces = []
        _workspaces = d.pop("workspaces")
        for workspaces_item_data in _workspaces:
            workspaces_item = SlackWorkspaceRequest.from_dict(workspaces_item_data)

            workspaces.append(workspaces_item)

        users = []
        _users = d.pop("users")
        for users_item_data in _users:
            users_item = SlackUsergroupsUser.from_dict(users_item_data)

            users.append(users_item)

        slack_usergroups_reconcile_payload = cls(
            workspaces=workspaces,
            users=users,
        )

        slack_usergroups_reconcile_payload.additional_properties = d
        return slack_usergroups_reconcile_payload

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
