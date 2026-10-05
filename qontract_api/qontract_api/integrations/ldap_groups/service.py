"""ldap-groups reconciliation service."""

from __future__ import annotations

import operator
from typing import TYPE_CHECKING

from qontract_utils.differ import DiffResult, diff_iterables

from qontract_api.integrations.ldap_groups.metrics import (
    INTEGRATION_NAME,
    ldap_groups_reconcile_errors,
    ldap_groups_reconciled,
)
from qontract_api.integrations.ldap_groups.schemas import (
    LdapGroupsAction,
    LdapGroupsActionCreate,
    LdapGroupsActionDelete,
    LdapGroupsActionUpdate,
    LdapGroupsTaskResult,
)
from qontract_api.internal_groups.internal_groups_client_factory import (
    create_internal_groups_workspace_client,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.integrations.ldap_groups.domain import Group
    from qontract_api.internal_groups.domain import InternalGroupsConnectionSecret
    from qontract_api.internal_groups.internal_groups_workspace_client import (
        InternalGroupsWorkspaceClient,
    )
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class LdapGroupsService:
    """Reconcile Internal Groups against desired App-Interface state."""

    def __init__(
        self,
        cache: CacheBackend,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self.cache = cache
        self.secret_manager = secret_manager
        self.settings = settings

    @staticmethod
    def _action_for_create(group: Group) -> LdapGroupsActionCreate:
        return LdapGroupsActionCreate(
            name=group.name,
            members=[m.id for m in group.members],
            owners=[o.id for o in group.owners],
            notes=group.notes,
        )

    @staticmethod
    def _action_for_update(group: Group) -> LdapGroupsActionUpdate:
        return LdapGroupsActionUpdate(
            name=group.name,
            members=[m.id for m in group.members],
            owners=[o.id for o in group.owners],
            notes=group.notes,
        )

    def _apply_diff(
        self,
        workspace_client: InternalGroupsWorkspaceClient,
        diff_result: DiffResult[Group, Group, str],
        managed_groups: set[str],
        *,
        dry_run: bool,
    ) -> tuple[list[LdapGroupsAction], list[LdapGroupsAction], list[str]]:
        actions: list[LdapGroupsAction] = []
        applied_actions: list[LdapGroupsAction] = []
        errors: list[str] = []

        for group_to_add in diff_result.add.values():
            create_action = self._action_for_create(group_to_add)
            actions.append(create_action)
            logger.info(
                "create_ldap_group",
                name=group_to_add.name,
                members=create_action.members,
                owners=create_action.owners,
                notes=create_action.notes,
            )
            if dry_run:
                continue
            try:
                workspace_client.create_group(group_to_add)
                applied_actions.append(create_action)
                managed_groups.add(group_to_add.name)
            except Exception as err:
                msg = f"failed to create group {group_to_add.name}: {err}"
                logger.exception(msg)
                errors.append(msg)

        for group_to_remove in diff_result.delete.values():
            delete_action = LdapGroupsActionDelete(name=group_to_remove.name)
            actions.append(delete_action)
            logger.info("delete_ldap_group", name=group_to_remove.name)
            if dry_run:
                continue
            try:
                workspace_client.delete_group(group_to_remove.name)
                applied_actions.append(delete_action)
                managed_groups.discard(group_to_remove.name)
            except Exception as err:
                msg = f"failed to delete group {group_to_remove.name}: {err}"
                logger.exception(msg)
                errors.append(msg)

        for diff_pair in diff_result.change.values():
            group_to_update = diff_pair.desired
            update_action = self._action_for_update(group_to_update)
            actions.append(update_action)
            logger.info(
                "update_ldap_group",
                name=group_to_update.name,
                members=update_action.members,
                owners=update_action.owners,
                notes=update_action.notes,
            )
            if dry_run:
                continue
            try:
                workspace_client.update_group(group_to_update)
                applied_actions.append(update_action)
            except Exception as err:
                msg = f"failed to update group {group_to_update.name}: {err}"
                logger.exception(msg)
                errors.append(msg)

        return actions, applied_actions, errors

    def reconcile(
        self,
        connection: InternalGroupsConnectionSecret,
        desired_groups: list[Group],
        managed_group_names: list[str],
        *,
        dry_run: bool = True,
    ) -> LdapGroupsTaskResult:
        group_names = set(managed_group_names)
        group_names.update(g.name for g in desired_groups)

        with create_internal_groups_workspace_client(
            connection, self.cache, self.secret_manager, self.settings
        ) as workspace_client:
            current_groups = [
                group
                for name in group_names
                if (group := workspace_client.get_group(name)) is not None
            ]
            managed_groups = {g.name for g in current_groups}

            diff_result = diff_iterables(
                current_groups,
                desired_groups,
                key=lambda g: g.name,
                equal=operator.eq,
            )

            actions, applied_actions, errors = self._apply_diff(
                workspace_client,
                diff_result,
                managed_groups,
                dry_run=dry_run,
            )

        if errors:
            ldap_groups_reconcile_errors.labels(INTEGRATION_NAME).inc()
        else:
            ldap_groups_reconciled.labels(INTEGRATION_NAME).inc()

        return LdapGroupsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
            updated_managed_groups=sorted(managed_groups),
        )
