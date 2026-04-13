from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TypeVar, cast

from attrs import define as _attrs_define
from attrs import field as _attrs_field

from ..models.task_status import TaskStatus
from ..types import UNSET, Unset

if TYPE_CHECKING:
    from ..models.glitchtip_action_add_project_to_team import (
        GlitchtipActionAddProjectToTeam,
    )
    from ..models.glitchtip_action_add_user_to_team import GlitchtipActionAddUserToTeam
    from ..models.glitchtip_action_create_organization import (
        GlitchtipActionCreateOrganization,
    )
    from ..models.glitchtip_action_create_project import GlitchtipActionCreateProject
    from ..models.glitchtip_action_create_team import GlitchtipActionCreateTeam
    from ..models.glitchtip_action_delete_organization import (
        GlitchtipActionDeleteOrganization,
    )
    from ..models.glitchtip_action_delete_project import GlitchtipActionDeleteProject
    from ..models.glitchtip_action_delete_team import GlitchtipActionDeleteTeam
    from ..models.glitchtip_action_delete_user import GlitchtipActionDeleteUser
    from ..models.glitchtip_action_invite_user import GlitchtipActionInviteUser
    from ..models.glitchtip_action_remove_project_from_team import (
        GlitchtipActionRemoveProjectFromTeam,
    )
    from ..models.glitchtip_action_remove_user_from_team import (
        GlitchtipActionRemoveUserFromTeam,
    )
    from ..models.glitchtip_action_update_project import GlitchtipActionUpdateProject
    from ..models.glitchtip_action_update_user_role import GlitchtipActionUpdateUserRole


T = TypeVar("T", bound="GlitchtipTaskResult")


@_attrs_define
class GlitchtipTaskResult:
    """Result model for completed Glitchtip reconciliation task.

    Attributes:
        status (TaskStatus): Status for background tasks.

            Used across all async API endpoints to indicate task execution state.
        actions (list[GlitchtipActionAddProjectToTeam | GlitchtipActionAddUserToTeam | GlitchtipActionCreateOrganization
            | GlitchtipActionCreateProject | GlitchtipActionCreateTeam | GlitchtipActionDeleteOrganization |
            GlitchtipActionDeleteProject | GlitchtipActionDeleteTeam | GlitchtipActionDeleteUser | GlitchtipActionInviteUser
            | GlitchtipActionRemoveProjectFromTeam | GlitchtipActionRemoveUserFromTeam | GlitchtipActionUpdateProject |
            GlitchtipActionUpdateUserRole] | Unset): All actions calculated (desired - current), including any that failed
            to apply.
        applied_actions (list[GlitchtipActionAddProjectToTeam | GlitchtipActionAddUserToTeam |
            GlitchtipActionCreateOrganization | GlitchtipActionCreateProject | GlitchtipActionCreateTeam |
            GlitchtipActionDeleteOrganization | GlitchtipActionDeleteProject | GlitchtipActionDeleteTeam |
            GlitchtipActionDeleteUser | GlitchtipActionInviteUser | GlitchtipActionRemoveProjectFromTeam |
            GlitchtipActionRemoveUserFromTeam | GlitchtipActionUpdateProject | GlitchtipActionUpdateUserRole] | Unset):
            Actions that were successfully applied (subset of actions, empty on dry_run).
        applied_count (int | Unset): Number of actions actually applied (0 if dry_run=True) Default: 0.
        errors (list[str] | Unset): List of errors encountered during reconciliation
    """

    status: TaskStatus
    actions: (
        list[
            GlitchtipActionAddProjectToTeam
            | GlitchtipActionAddUserToTeam
            | GlitchtipActionCreateOrganization
            | GlitchtipActionCreateProject
            | GlitchtipActionCreateTeam
            | GlitchtipActionDeleteOrganization
            | GlitchtipActionDeleteProject
            | GlitchtipActionDeleteTeam
            | GlitchtipActionDeleteUser
            | GlitchtipActionInviteUser
            | GlitchtipActionRemoveProjectFromTeam
            | GlitchtipActionRemoveUserFromTeam
            | GlitchtipActionUpdateProject
            | GlitchtipActionUpdateUserRole
        ]
        | Unset
    ) = UNSET
    applied_actions: (
        list[
            GlitchtipActionAddProjectToTeam
            | GlitchtipActionAddUserToTeam
            | GlitchtipActionCreateOrganization
            | GlitchtipActionCreateProject
            | GlitchtipActionCreateTeam
            | GlitchtipActionDeleteOrganization
            | GlitchtipActionDeleteProject
            | GlitchtipActionDeleteTeam
            | GlitchtipActionDeleteUser
            | GlitchtipActionInviteUser
            | GlitchtipActionRemoveProjectFromTeam
            | GlitchtipActionRemoveUserFromTeam
            | GlitchtipActionUpdateProject
            | GlitchtipActionUpdateUserRole
        ]
        | Unset
    ) = UNSET
    applied_count: int | Unset = 0
    errors: list[str] | Unset = UNSET
    additional_properties: dict[str, Any] = _attrs_field(init=False, factory=dict)

    def to_dict(self) -> dict[str, Any]:
        from ..models.glitchtip_action_add_project_to_team import (
            GlitchtipActionAddProjectToTeam,
        )
        from ..models.glitchtip_action_add_user_to_team import (
            GlitchtipActionAddUserToTeam,
        )
        from ..models.glitchtip_action_create_organization import (
            GlitchtipActionCreateOrganization,
        )
        from ..models.glitchtip_action_create_project import (
            GlitchtipActionCreateProject,
        )
        from ..models.glitchtip_action_create_team import GlitchtipActionCreateTeam
        from ..models.glitchtip_action_delete_organization import (
            GlitchtipActionDeleteOrganization,
        )
        from ..models.glitchtip_action_delete_project import (
            GlitchtipActionDeleteProject,
        )
        from ..models.glitchtip_action_delete_team import GlitchtipActionDeleteTeam
        from ..models.glitchtip_action_delete_user import GlitchtipActionDeleteUser
        from ..models.glitchtip_action_invite_user import GlitchtipActionInviteUser
        from ..models.glitchtip_action_remove_user_from_team import (
            GlitchtipActionRemoveUserFromTeam,
        )
        from ..models.glitchtip_action_update_project import (
            GlitchtipActionUpdateProject,
        )
        from ..models.glitchtip_action_update_user_role import (
            GlitchtipActionUpdateUserRole,
        )

        status = self.status.value

        actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.actions, Unset):
            actions = []
            for actions_item_data in self.actions:
                actions_item: dict[str, Any]
                if isinstance(actions_item_data, GlitchtipActionCreateOrganization):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionDeleteOrganization):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionInviteUser):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionDeleteUser):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionUpdateUserRole):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionCreateTeam):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionDeleteTeam):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionAddUserToTeam):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionRemoveUserFromTeam):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionCreateProject):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionUpdateProject):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionDeleteProject):
                    actions_item = actions_item_data.to_dict()
                elif isinstance(actions_item_data, GlitchtipActionAddProjectToTeam):
                    actions_item = actions_item_data.to_dict()
                else:
                    actions_item = actions_item_data.to_dict()

                actions.append(actions_item)

        applied_actions: list[dict[str, Any]] | Unset = UNSET
        if not isinstance(self.applied_actions, Unset):
            applied_actions = []
            for applied_actions_item_data in self.applied_actions:
                applied_actions_item: dict[str, Any]
                if isinstance(
                    applied_actions_item_data, GlitchtipActionCreateOrganization
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionDeleteOrganization
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(applied_actions_item_data, GlitchtipActionInviteUser):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(applied_actions_item_data, GlitchtipActionDeleteUser):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionUpdateUserRole
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(applied_actions_item_data, GlitchtipActionCreateTeam):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(applied_actions_item_data, GlitchtipActionDeleteTeam):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionAddUserToTeam
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionRemoveUserFromTeam
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionCreateProject
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionUpdateProject
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionDeleteProject
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                elif isinstance(
                    applied_actions_item_data, GlitchtipActionAddProjectToTeam
                ):
                    applied_actions_item = applied_actions_item_data.to_dict()
                else:
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
        from ..models.glitchtip_action_add_project_to_team import (
            GlitchtipActionAddProjectToTeam,
        )
        from ..models.glitchtip_action_add_user_to_team import (
            GlitchtipActionAddUserToTeam,
        )
        from ..models.glitchtip_action_create_organization import (
            GlitchtipActionCreateOrganization,
        )
        from ..models.glitchtip_action_create_project import (
            GlitchtipActionCreateProject,
        )
        from ..models.glitchtip_action_create_team import GlitchtipActionCreateTeam
        from ..models.glitchtip_action_delete_organization import (
            GlitchtipActionDeleteOrganization,
        )
        from ..models.glitchtip_action_delete_project import (
            GlitchtipActionDeleteProject,
        )
        from ..models.glitchtip_action_delete_team import GlitchtipActionDeleteTeam
        from ..models.glitchtip_action_delete_user import GlitchtipActionDeleteUser
        from ..models.glitchtip_action_invite_user import GlitchtipActionInviteUser
        from ..models.glitchtip_action_remove_project_from_team import (
            GlitchtipActionRemoveProjectFromTeam,
        )
        from ..models.glitchtip_action_remove_user_from_team import (
            GlitchtipActionRemoveUserFromTeam,
        )
        from ..models.glitchtip_action_update_project import (
            GlitchtipActionUpdateProject,
        )
        from ..models.glitchtip_action_update_user_role import (
            GlitchtipActionUpdateUserRole,
        )

        d = dict(src_dict)
        status = TaskStatus(d.pop("status"))

        _actions = d.pop("actions", UNSET)
        actions: (
            list[
                GlitchtipActionAddProjectToTeam
                | GlitchtipActionAddUserToTeam
                | GlitchtipActionCreateOrganization
                | GlitchtipActionCreateProject
                | GlitchtipActionCreateTeam
                | GlitchtipActionDeleteOrganization
                | GlitchtipActionDeleteProject
                | GlitchtipActionDeleteTeam
                | GlitchtipActionDeleteUser
                | GlitchtipActionInviteUser
                | GlitchtipActionRemoveProjectFromTeam
                | GlitchtipActionRemoveUserFromTeam
                | GlitchtipActionUpdateProject
                | GlitchtipActionUpdateUserRole
            ]
            | Unset
        ) = UNSET
        if _actions is not UNSET:
            actions = []
            for actions_item_data in _actions:

                def _parse_actions_item(
                    data: object,
                ) -> (
                    GlitchtipActionAddProjectToTeam
                    | GlitchtipActionAddUserToTeam
                    | GlitchtipActionCreateOrganization
                    | GlitchtipActionCreateProject
                    | GlitchtipActionCreateTeam
                    | GlitchtipActionDeleteOrganization
                    | GlitchtipActionDeleteProject
                    | GlitchtipActionDeleteTeam
                    | GlitchtipActionDeleteUser
                    | GlitchtipActionInviteUser
                    | GlitchtipActionRemoveProjectFromTeam
                    | GlitchtipActionRemoveUserFromTeam
                    | GlitchtipActionUpdateProject
                    | GlitchtipActionUpdateUserRole
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_0 = (
                            GlitchtipActionCreateOrganization.from_dict(data)
                        )

                        return actions_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_1 = (
                            GlitchtipActionDeleteOrganization.from_dict(data)
                        )

                        return actions_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_2 = GlitchtipActionInviteUser.from_dict(data)

                        return actions_item_type_2
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_3 = GlitchtipActionDeleteUser.from_dict(data)

                        return actions_item_type_3
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_4 = GlitchtipActionUpdateUserRole.from_dict(
                            data
                        )

                        return actions_item_type_4
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_5 = GlitchtipActionCreateTeam.from_dict(data)

                        return actions_item_type_5
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_6 = GlitchtipActionDeleteTeam.from_dict(data)

                        return actions_item_type_6
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_7 = GlitchtipActionAddUserToTeam.from_dict(
                            data
                        )

                        return actions_item_type_7
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_8 = (
                            GlitchtipActionRemoveUserFromTeam.from_dict(data)
                        )

                        return actions_item_type_8
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_9 = GlitchtipActionCreateProject.from_dict(
                            data
                        )

                        return actions_item_type_9
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_10 = GlitchtipActionUpdateProject.from_dict(
                            data
                        )

                        return actions_item_type_10
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_11 = GlitchtipActionDeleteProject.from_dict(
                            data
                        )

                        return actions_item_type_11
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        actions_item_type_12 = (
                            GlitchtipActionAddProjectToTeam.from_dict(data)
                        )

                        return actions_item_type_12
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    actions_item_type_13 = (
                        GlitchtipActionRemoveProjectFromTeam.from_dict(data)
                    )

                    return actions_item_type_13

                actions_item = _parse_actions_item(actions_item_data)

                actions.append(actions_item)

        _applied_actions = d.pop("applied_actions", UNSET)
        applied_actions: (
            list[
                GlitchtipActionAddProjectToTeam
                | GlitchtipActionAddUserToTeam
                | GlitchtipActionCreateOrganization
                | GlitchtipActionCreateProject
                | GlitchtipActionCreateTeam
                | GlitchtipActionDeleteOrganization
                | GlitchtipActionDeleteProject
                | GlitchtipActionDeleteTeam
                | GlitchtipActionDeleteUser
                | GlitchtipActionInviteUser
                | GlitchtipActionRemoveProjectFromTeam
                | GlitchtipActionRemoveUserFromTeam
                | GlitchtipActionUpdateProject
                | GlitchtipActionUpdateUserRole
            ]
            | Unset
        ) = UNSET
        if _applied_actions is not UNSET:
            applied_actions = []
            for applied_actions_item_data in _applied_actions:

                def _parse_applied_actions_item(
                    data: object,
                ) -> (
                    GlitchtipActionAddProjectToTeam
                    | GlitchtipActionAddUserToTeam
                    | GlitchtipActionCreateOrganization
                    | GlitchtipActionCreateProject
                    | GlitchtipActionCreateTeam
                    | GlitchtipActionDeleteOrganization
                    | GlitchtipActionDeleteProject
                    | GlitchtipActionDeleteTeam
                    | GlitchtipActionDeleteUser
                    | GlitchtipActionInviteUser
                    | GlitchtipActionRemoveProjectFromTeam
                    | GlitchtipActionRemoveUserFromTeam
                    | GlitchtipActionUpdateProject
                    | GlitchtipActionUpdateUserRole
                ):
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_0 = (
                            GlitchtipActionCreateOrganization.from_dict(data)
                        )

                        return applied_actions_item_type_0
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_1 = (
                            GlitchtipActionDeleteOrganization.from_dict(data)
                        )

                        return applied_actions_item_type_1
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_2 = (
                            GlitchtipActionInviteUser.from_dict(data)
                        )

                        return applied_actions_item_type_2
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_3 = (
                            GlitchtipActionDeleteUser.from_dict(data)
                        )

                        return applied_actions_item_type_3
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_4 = (
                            GlitchtipActionUpdateUserRole.from_dict(data)
                        )

                        return applied_actions_item_type_4
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_5 = (
                            GlitchtipActionCreateTeam.from_dict(data)
                        )

                        return applied_actions_item_type_5
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_6 = (
                            GlitchtipActionDeleteTeam.from_dict(data)
                        )

                        return applied_actions_item_type_6
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_7 = (
                            GlitchtipActionAddUserToTeam.from_dict(data)
                        )

                        return applied_actions_item_type_7
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_8 = (
                            GlitchtipActionRemoveUserFromTeam.from_dict(data)
                        )

                        return applied_actions_item_type_8
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_9 = (
                            GlitchtipActionCreateProject.from_dict(data)
                        )

                        return applied_actions_item_type_9
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_10 = (
                            GlitchtipActionUpdateProject.from_dict(data)
                        )

                        return applied_actions_item_type_10
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_11 = (
                            GlitchtipActionDeleteProject.from_dict(data)
                        )

                        return applied_actions_item_type_11
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    try:
                        if not isinstance(data, dict):
                            raise TypeError()
                        applied_actions_item_type_12 = (
                            GlitchtipActionAddProjectToTeam.from_dict(data)
                        )

                        return applied_actions_item_type_12
                    except (TypeError, ValueError, AttributeError, KeyError):
                        pass
                    if not isinstance(data, dict):
                        raise TypeError()
                    applied_actions_item_type_13 = (
                        GlitchtipActionRemoveProjectFromTeam.from_dict(data)
                    )

                    return applied_actions_item_type_13

                applied_actions_item = _parse_applied_actions_item(
                    applied_actions_item_data
                )

                applied_actions.append(applied_actions_item)

        applied_count = d.pop("applied_count", UNSET)

        errors = cast(list[str], d.pop("errors", UNSET))

        glitchtip_task_result = cls(
            status=status,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=applied_count,
            errors=errors,
        )

        glitchtip_task_result.additional_properties = d
        return glitchtip_task_result

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
