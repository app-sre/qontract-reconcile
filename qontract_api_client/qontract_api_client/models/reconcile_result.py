from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.reconcile_action_enable_support import ReconcileActionEnableSupport
    from ..models.reconcile_action_move_ou import ReconcileActionMoveOU
    from ..models.reconcile_action_request_quota import ReconcileActionRequestQuota
    from ..models.reconcile_action_set_alias import ReconcileActionSetAlias
    from ..models.reconcile_action_set_regions import ReconcileActionSetRegions
    from ..models.reconcile_action_set_security_contact import (
        ReconcileActionSetSecurityContact,
    )
    from ..models.reconcile_action_tag import ReconcileActionTag


T = TypeVar("T", bound="ReconcileResult")


@_attrs_define
class ReconcileResult:
    """Result for GET /reconcile/{task_id}.

    Success/failure status for account reconciliation.

        Attributes:
            status (TaskStatus): Status for background tasks.

                Used across all async API endpoints to indicate task execution state.
            actions (list[ReconcileActionEnableSupport | ReconcileActionMoveOU | ReconcileActionRequestQuota |
                ReconcileActionSetAlias | ReconcileActionSetRegions | ReconcileActionSetSecurityContact | ReconcileActionTag] |
                Unset): Reconciliation actions performed
            applied_count (int | Unset): Number of actions actually applied (0 if dry_run=True) Default: 0.
            errors (list[str] | Unset): List of errors encountered during reconciliation
    """

    status: TaskStatus
    actions: (
        list[
            ReconcileActionEnableSupport
            | ReconcileActionMoveOU
            | ReconcileActionRequestQuota
            | ReconcileActionSetAlias
            | ReconcileActionSetRegions
            | ReconcileActionSetSecurityContact
            | ReconcileActionTag
        ]
        | Unset
    ) = UNSET
    applied_count: int | Unset = 0
    errors: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.reconcile_action_enable_support import (
            ReconcileActionEnableSupport,
        )
        from ..models.reconcile_action_move_ou import ReconcileActionMoveOU
        from ..models.reconcile_action_request_quota import ReconcileActionRequestQuota
        from ..models.reconcile_action_set_alias import ReconcileActionSetAlias
        from ..models.reconcile_action_set_security_contact import (
            ReconcileActionSetSecurityContact,
        )
        from ..models.reconcile_action_tag import ReconcileActionTag

        status = self.status.value

        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item: dict[str, Any]
                if isinstance(actions_item_data, ReconcileActionTag):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, ReconcileActionMoveOU):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, ReconcileActionSetAlias):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, ReconcileActionRequestQuota):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, ReconcileActionEnableSupport):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, ReconcileActionSetSecurityContact):
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
        from ..models.reconcile_action_enable_support import (
            ReconcileActionEnableSupport,
        )
        from ..models.reconcile_action_move_ou import ReconcileActionMoveOU
        from ..models.reconcile_action_request_quota import ReconcileActionRequestQuota
        from ..models.reconcile_action_set_alias import ReconcileActionSetAlias
        from ..models.reconcile_action_set_regions import ReconcileActionSetRegions
        from ..models.reconcile_action_set_security_contact import (
            ReconcileActionSetSecurityContact,
        )
        from ..models.reconcile_action_tag import ReconcileActionTag

        d = dict(src_dict)
        status = TaskStatus(d.pop("status"))

        _actions = d.pop("actions", UNSET)
        actions: (
            list[
                ReconcileActionEnableSupport
                | ReconcileActionMoveOU
                | ReconcileActionRequestQuota
                | ReconcileActionSetAlias
                | ReconcileActionSetRegions
                | ReconcileActionSetSecurityContact
                | ReconcileActionTag
            ]
            | Unset
        ) = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:

                def _parse_actions_item(
                    data: object,
                ) -> (
                    ReconcileActionEnableSupport
                    | ReconcileActionMoveOU
                    | ReconcileActionRequestQuota
                    | ReconcileActionSetAlias
                    | ReconcileActionSetRegions
                    | ReconcileActionSetSecurityContact
                    | ReconcileActionTag
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_0 = ReconcileActionTag.from_dict(data)

                        return actions_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_1 = ReconcileActionMoveOU.from_dict(data)

                        return actions_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_2 = ReconcileActionSetAlias.from_dict(data)

                        return actions_item_type_2
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_3 = ReconcileActionRequestQuota.from_dict(
                            data
                        )

                        return actions_item_type_3
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_4 = ReconcileActionEnableSupport.from_dict(
                            data
                        )

                        return actions_item_type_4
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_5 = (
                            ReconcileActionSetSecurityContact.from_dict(data)
                        )

                        return actions_item_type_5
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    actions_item_type_6 = ReconcileActionSetRegions.from_dict(data)

                    return actions_item_type_6

                actions_item = _parse_actions_item(actions_item_data)

                actions.append(actions_item)

        applied_count = d.pop("applied_count", UNSET)

        errors = cast(list[str], d.pop("errors", UNSET))

        reconcile_result = cls(
            status=status,
            actions=actions,
            applied_count=applied_count,
            errors=errors,
        )

        reconcile_result.additional_properties = d
        return reconcile_result

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
