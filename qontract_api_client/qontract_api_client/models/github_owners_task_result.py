from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.github_owner_action_add_owner import GithubOwnerActionAddOwner


T = TypeVar("T", bound="GithubOwnersTaskResult")


@_attrs_define
class GithubOwnersTaskResult:
    """Result model for a completed github-owners reconciliation task.

    Returned by GET /reconcile/{task_id}.

        Attributes:
            status (TaskStatus): Status for background tasks.

                Used across all async API endpoints to indicate task execution state.
            actions (list[GithubOwnerActionAddOwner] | Unset): All actions calculated (desired - current), including any
                that failed to apply.
            applied_actions (list[GithubOwnerActionAddOwner] | Unset): Actions that were successfully applied (non-dry-run
                only).
            applied_count (int | Unset): Number of actions actually applied (0 if dry_run=True) Default: 0.
            errors (list[str] | Unset): List of errors encountered during reconciliation
    """

    status: TaskStatus
    actions: list[GithubOwnerActionAddOwner] | Unset = UNSET
    applied_actions: list[GithubOwnerActionAddOwner] | Unset = UNSET
    applied_count: int | Unset = 0
    errors: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        status = self.status.value

        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item = actions_item_data.to_dict()
                actions.append(actions_item)

        applied_actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.applied_actions, Unset):
            applied_actions = []
            for applied_actions_item_data in self.applied_actions:
                applied_actions_item = applied_actions_item_data.to_dict()
                applied_actions.append(applied_actions_item)

        applied_count = self.applied_count

        errors: list[str] | Unset = UNSET
        if not isinstance(self.errors, Unset):
            errors = self.errors

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "status": status,
        })
        if actions is not UNSET:
            field_dict["actions"] = actions
        if applied_actions is not UNSET:
            field_dict["applied_actions"] = applied_actions
        if applied_count is not UNSET:
            field_dict["applied_count"] = applied_count
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.github_owner_action_add_owner import GithubOwnerActionAddOwner

        d = dict(src_dict)
        status = TaskStatus(d.pop("status"))

        _actions = d.pop("actions", UNSET)
        actions: list[GithubOwnerActionAddOwner] | Unset = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:
                actions_item = GithubOwnerActionAddOwner.from_dict(actions_item_data)

                actions.append(actions_item)

        _applied_actions = d.pop("applied_actions", UNSET)
        applied_actions: list[GithubOwnerActionAddOwner] | Unset = UNSET
        if _applied_actions is not UNSET:
            applied_actions = []
            for applied_actions_item_data in _applied_actions:
                applied_actions_item = GithubOwnerActionAddOwner.from_dict(
                    applied_actions_item_data
                )

                applied_actions.append(applied_actions_item)

        applied_count = d.pop("applied_count", UNSET)

        errors = cast(list[str], d.pop("errors", UNSET))

        github_owners_task_result = cls(
            status=status,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=applied_count,
            errors=errors,
        )

        github_owners_task_result.additional_properties = d
        return github_owners_task_result

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
