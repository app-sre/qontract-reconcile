from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.slack_usergroup_action_create import SlackUsergroupActionCreate
    from ..models.slack_usergroup_action_update_metadata import (
        SlackUsergroupActionUpdateMetadata,
    )
    from ..models.slack_usergroup_action_update_users import (
        SlackUsergroupActionUpdateUsers,
    )


T = TypeVar("T", bound="SlackUsergroupsTaskResult")


@_attrs_define
class SlackUsergroupsTaskResult:
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.
    Contains the reconciliation results and execution status.

        Attributes:
            status (TaskStatus): Status for background tasks.

                Used across all async API endpoints to indicate task execution state.
            actions (list[SlackUsergroupActionCreate | SlackUsergroupActionUpdateMetadata | SlackUsergroupActionUpdateUsers]
                | Unset): List of actions calculated/performed
            applied_count (int | Unset): Number of actions actually applied (0 if dry_run=True) Default: 0.
            errors (list[str] | None | Unset): List of errors encountered during reconciliation
    """

    status: TaskStatus
    actions: (
        list[
            SlackUsergroupActionCreate
            | SlackUsergroupActionUpdateMetadata
            | SlackUsergroupActionUpdateUsers
        ]
        | Unset
    ) = UNSET
    applied_count: int | Unset = 0
    errors: list[str] | None | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.slack_usergroup_action_create import SlackUsergroupActionCreate
        from ..models.slack_usergroup_action_update_users import (
            SlackUsergroupActionUpdateUsers,
        )

        status = self.status.value

        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item: dict[str, Any]
                if isinstance(actions_item_data, SlackUsergroupActionCreate):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, SlackUsergroupActionUpdateUsers):
                    actions_item = actions_item_data.to_dict()
                else:
                    actions_item = actions_item_data.to_dict()

                actions.append(actions_item)

        applied_count = self.applied_count

        errors: list[str] | None | Unset
        if isinstance(self.errors, Unset):
            errors = UNSET
        elif isinstance(self.errors, list):
            errors = self.errors

        else:
            errors = self.errors

        field_dict: dict[str, Any] = {}
        field_dict.update(self.additional_properties)
        field_dict.update({
            "status": status,
        })
        if actions is not UNSET:
            field_dict["actions"] = actions
        if applied_count is not UNSET:
            field_dict["applied_count"] = applied_count
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.slack_usergroup_action_create import SlackUsergroupActionCreate
        from ..models.slack_usergroup_action_update_metadata import (
            SlackUsergroupActionUpdateMetadata,
        )
        from ..models.slack_usergroup_action_update_users import (
            SlackUsergroupActionUpdateUsers,
        )

        d = dict(src_dict)
        status = TaskStatus(d.pop("status"))

        _actions = d.pop("actions", UNSET)
        actions: (
            list[
                SlackUsergroupActionCreate
                | SlackUsergroupActionUpdateMetadata
                | SlackUsergroupActionUpdateUsers
            ]
            | Unset
        ) = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:

                def _parse_actions_item(
                    data: object,
                ) -> (
                    SlackUsergroupActionCreate
                    | SlackUsergroupActionUpdateMetadata
                    | SlackUsergroupActionUpdateUsers
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_0 = SlackUsergroupActionCreate.from_dict(data)

                        return actions_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_1 = SlackUsergroupActionUpdateUsers.from_dict(
                            data
                        )

                        return actions_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    actions_item_type_2 = SlackUsergroupActionUpdateMetadata.from_dict(
                        data
                    )

                    return actions_item_type_2

                actions_item = _parse_actions_item(actions_item_data)

                actions.append(actions_item)

        applied_count = d.pop("applied_count", UNSET)

        def _parse_errors(data: object) -> list[str] | None | Unset:
            if data is None:
                return data
            if isinstance(data, Unset):
                return data
            try:
                if not isinstance(data, list):
                    raise TypeError()
                errors_type_0 = cast(list[str], data)

                return errors_type_0
            except (TypeError, ValueError, AttributeError, KeyError):
                pass
            return cast(list[str] | None | Unset, data)

        errors = _parse_errors(d.pop("errors", UNSET))

        slack_usergroups_task_result = cls(
            status=status,
            actions=actions,
            applied_count=applied_count,
            errors=errors,
        )

        slack_usergroups_task_result.additional_properties = d
        return slack_usergroups_task_result

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
