"""GitLab group membership reconciliation service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from qontract_utils.differ import diff_mappings
from qontract_utils.gitlab_api import GitlabUserNotFoundError

from qontract_api.gitlab.gitlab_client_factory import create_gitlab_workspace_client
from qontract_api.integrations.gitlab_members.schemas import (
    GitlabMemberAction,
    GitlabMemberActionAdd,
    GitlabMemberActionChangeAccess,
    GitlabMemberActionRemove,
    GitlabMembersTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from qontract_utils.gitlab_api import GitlabGroupMember

    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.gitlab.gitlab_workspace_client import GitlabWorkspaceClient
    from qontract_api.integrations.gitlab_members.domain import (
        GitlabMembersGroupConfig,
        GitlabMembersInstanceConfig,
    )
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class GitlabMembersService:
    """Service for reconciling GitLab group membership.

    Uses Dependency Injection to keep the service decoupled from secret backends.
    Talks to Layer 2 GitlabWorkspaceClient — never calls Layer 1 GitlabApi directly.
    """

    def __init__(
        self,
        secret_manager: SecretManager,
        cache: CacheBackend,
        settings: Settings,
        workspace_client_factory: Callable[..., GitlabWorkspaceClient] | None = None,
    ) -> None:
        self.secret_manager = secret_manager
        self.cache = cache
        self.settings = settings
        self._workspace_client_factory = (
            workspace_client_factory or create_gitlab_workspace_client
        )

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_actions(
        client: GitlabWorkspaceClient,
        instance_name: str,
        group_cfg: GitlabMembersGroupConfig,
        current_members: list[GitlabGroupMember],
    ) -> tuple[list[GitlabMemberAction], list[str]]:
        current = {m.username: m for m in current_members}
        desired = {m.username: m for m in group_cfg.members}

        diff = diff_mappings(
            current=current,
            desired=desired,
            equal=lambda current, desired: (
                current.access_level == desired.access_level.to_access_level()
            ),
        )

        actions: list[GitlabMemberAction] = []
        errors: list[str] = []

        for username, member in diff.add.items():
            try:
                user = client.get_user_by_username(username)
            except GitlabUserNotFoundError:
                errors.append(
                    f"{instance_name}/{group_cfg.group}/{username}: GitLab user not found"
                )
                continue
            actions.append(
                GitlabMemberActionAdd(
                    instance=instance_name,
                    group=group_cfg.group,
                    username=username,
                    user_id=user.id,
                    access_level=member.access_level,
                )
            )

        actions.extend(
            GitlabMemberActionRemove(
                instance=instance_name,
                group=group_cfg.group,
                username=username,
                member_id=member.id,
            )
            for username, member in diff.delete.items()
        )
        actions.extend(
            GitlabMemberActionChangeAccess(
                instance=instance_name,
                group=group_cfg.group,
                username=username,
                member_id=pair.current.id,
                access_level=pair.desired.access_level,
            )
            for username, pair in diff.change.items()
        )
        return actions, errors

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def _apply_actions(
        self,
        client: GitlabWorkspaceClient,
        instance_name: str,
        group: str,
        actions: list[GitlabMemberAction],
    ) -> tuple[list[GitlabMemberAction], list[str]]:
        applied: list[GitlabMemberAction] = []
        errors: list[str] = []

        for action in actions:
            try:
                self._execute_action(client, action)
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{instance_name}/{group}/{action.username}/"
                    f"{action.action_type}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)
        return applied, errors

    @staticmethod
    def _execute_action(
        client: GitlabWorkspaceClient,
        action: GitlabMemberAction,
    ) -> None:
        match action:
            case GitlabMemberActionAdd():
                logger.info(
                    f"Adding {action.username} to {action.instance}/{action.group}",
                    action_type=action.action_type,
                )
                client.add_group_member(
                    action.group, action.user_id, action.access_level
                )
            case GitlabMemberActionRemove():
                logger.info(
                    f"Removing {action.username} from {action.instance}/{action.group}",
                    action_type=action.action_type,
                )
                client.remove_group_member(action.group, action.member_id)
            case GitlabMemberActionChangeAccess():
                logger.info(
                    f"Changing access for {action.username} in "
                    f"{action.instance}/{action.group} to {action.access_level}",
                    action_type=action.action_type,
                )
                client.update_group_member_access(
                    action.group, action.member_id, action.access_level
                )

    # ------------------------------------------------------------------
    # Per-group / per-instance reconciliation
    # ------------------------------------------------------------------

    def _reconcile_group(
        self,
        client: GitlabWorkspaceClient,
        instance_name: str,
        group_cfg: GitlabMembersGroupConfig,
        *,
        dry_run: bool,
    ) -> tuple[list[GitlabMemberAction], list[GitlabMemberAction], list[str]]:
        current_members = client.get_group_members(group_cfg.group)
        actions, errors = self._calculate_actions(
            client, instance_name, group_cfg, current_members
        )
        if not dry_run:
            applied, exec_errors = self._apply_actions(
                client, instance_name, group_cfg.group, actions
            )
            errors = [*errors, *exec_errors]
        else:
            applied = []
        return actions, applied, errors

    def _reconcile_instance(
        self,
        instance: GitlabMembersInstanceConfig,
        *,
        dry_run: bool,
    ) -> tuple[list[GitlabMemberAction], list[GitlabMemberAction], list[str]]:
        all_actions: list[GitlabMemberAction] = []
        all_applied: list[GitlabMemberAction] = []
        all_errors: list[str] = []

        with self._workspace_client_factory(
            secret=instance.token,
            url=instance.url,
            cache=self.cache,
            secret_manager=self.secret_manager,
            settings=self.settings,
            ssl_verify=instance.ssl_verify,
        ) as client:
            for group_cfg in instance.groups:
                try:
                    actions, applied, errors = self._reconcile_group(
                        client, instance.name, group_cfg, dry_run=dry_run
                    )
                    all_actions.extend(actions)
                    all_applied.extend(applied)
                    all_errors.extend(errors)
                except Exception as e:
                    error_msg = (
                        f"{instance.name}/{group_cfg.group}: Unexpected error: {e}"
                    )
                    logger.exception(error_msg)
                    all_errors.append(error_msg)

        return all_actions, all_applied, all_errors

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def reconcile(
        self,
        instances: list[GitlabMembersInstanceConfig],
        *,
        dry_run: bool = True,
    ) -> GitlabMembersTaskResult:
        """Reconcile GitLab group membership across all provided instances."""
        all_actions: list[GitlabMemberAction] = []
        all_applied: list[GitlabMemberAction] = []
        all_errors: list[str] = []

        for instance in instances:
            logger.info(f"Reconciling GitLab instance {instance.name}")
            try:
                actions, applied, errors = self._reconcile_instance(
                    instance, dry_run=dry_run
                )
                all_actions.extend(actions)
                all_applied.extend(applied)
                all_errors.extend(errors)
            except Exception as e:
                error_msg = f"{instance.name}: Unexpected error: {e}"
                logger.exception(error_msg)
                all_errors.append(error_msg)

        return GitlabMembersTaskResult(
            status=TaskStatus.FAILED if all_errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=all_applied,
            applied_count=len(all_applied),
            errors=all_errors,
        )
