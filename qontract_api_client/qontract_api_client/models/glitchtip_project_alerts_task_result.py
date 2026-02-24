from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_alert_action_create import GlitchtipAlertActionCreate
    from ..models.glitchtip_alert_action_delete import GlitchtipAlertActionDelete
    from ..models.glitchtip_alert_action_update import GlitchtipAlertActionUpdate


T = TypeVar("T", bound="GlitchtipProjectAlertsTaskResult")


@_attrs_define
class GlitchtipProjectAlertsTaskResult:
    """Result model for completed reconciliation task.

    Returned by GET /reconcile/{task_id}.

        Attributes:
            status (TaskStatus): Status for background tasks.

                Used across all async API endpoints to indicate task execution state.
            actions (list[GlitchtipAlertActionCreate | GlitchtipAlertActionDelete | GlitchtipAlertActionUpdate] | Unset):
                List of actions calculated/performed
            applied_count (int | Unset): Number of actions actually applied (0 if dry_run=True) Default: 0.
            errors (list[str] | Unset): List of errors encountered during reconciliation
    """

    status: TaskStatus
    actions: (
        list[
            GlitchtipAlertActionCreate
            | GlitchtipAlertActionDelete
            | GlitchtipAlertActionUpdate
        ]
        | Unset
    ) = UNSET
    applied_count: int | Unset = 0
    errors: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.glitchtip_alert_action_create import GlitchtipAlertActionCreate
        from ..models.glitchtip_alert_action_update import GlitchtipAlertActionUpdate

        status = self.status.value

        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item: dict[str, Any]
                if isinstance(actions_item_data, GlitchtipAlertActionCreate):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipAlertActionUpdate):
                    actions_item = actions_item_data.to_dict()
                else:
                    actions_item = actions_item_data.to_dict()

                actions.append(actions_item)

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
        if applied_count is not UNSET:
            field_dict["applied_count"] = applied_count
        if errors is not UNSET:
            field_dict["errors"] = errors

        return field_dict

    @classmethod
    def from_dict(cls: type[T], src_dict: Mapping[str, Any]) -> T:
        from ..models.glitchtip_alert_action_create import GlitchtipAlertActionCreate
        from ..models.glitchtip_alert_action_delete import GlitchtipAlertActionDelete
        from ..models.glitchtip_alert_action_update import GlitchtipAlertActionUpdate

        d = dict(src_dict)
        status = TaskStatus(d.pop("status"))

        _actions = d.pop("actions", UNSET)
        actions: (
            list[
                GlitchtipAlertActionCreate
                | GlitchtipAlertActionDelete
                | GlitchtipAlertActionUpdate
            ]
            | Unset
        ) = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:

                def _parse_actions_item(
                    data: object,
                ) -> (
                    GlitchtipAlertActionCreate
                    | GlitchtipAlertActionDelete
                    | GlitchtipAlertActionUpdate
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_0 = GlitchtipAlertActionCreate.from_dict(data)

                        return actions_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_1 = GlitchtipAlertActionUpdate.from_dict(data)

                        return actions_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    actions_item_type_2 = GlitchtipAlertActionDelete.from_dict(data)

                    return actions_item_type_2

                actions_item = _parse_actions_item(actions_item_data)

                actions.append(actions_item)

        applied_count = d.pop("applied_count", UNSET)

        errors = cast(list[str], d.pop("errors", UNSET))

        glitchtip_project_alerts_task_result = cls(
            status=status,
            actions=actions,
            applied_count=applied_count,
            errors=errors,
        )

        glitchtip_project_alerts_task_result.additional_properties = d
        return glitchtip_project_alerts_task_result

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
