from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.slack_workspace import SlackWorkspace


T = TypeVar("T", bound="SlackUsergroupsReconcileRequest")


@_attrs_define
class SlackUsergroupsReconcileRequest:
    """Request model for Slack usergroups reconciliation.

    POST requests always queue a background task (async execution).

        Attributes:
            workspaces (list[SlackWorkspace]): List of Slack workspaces with their usergroups
            dry_run (bool | Unset): If True, only calculate actions without executing. Default: True (safety first!)
                Default: True.
    """

    workspaces: list[SlackWorkspace]
    dry_run: bool | Unset = True
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        workspaces = []
        for workspaces_item_data in self.workspaces:
            workspaces_item = workspaces_item_data.to_dict()
            workspaces.append(workspaces_item)

        dry_run = self.dry_run

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "workspaces": workspaces,
        })
        if dry_run is not UNSET:
            field_dict["dry_run"] = dry_run

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.slack_workspace import SlackWorkspace

        d = dict(src_dict)
        workspaces = []
        _workspaces = d.pop("workspaces")
        for workspaces_item_data in _workspaces:
            workspaces_item = SlackWorkspace.from_dict(workspaces_item_data)

            workspaces.append(workspaces_item)

        dry_run = d.pop("dry_run", UNSET)

        slack_usergroups_reconcile_request = cls(
            workspaces=workspaces,
            dry_run=dry_run,
        )

        slack_usergroups_reconcile_request.additional_properties = d
        return slack_usergroups_reconcile_request

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
