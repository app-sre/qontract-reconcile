"""GitLab projects reconciliation service."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from qontract_utils.differ import diff_any_iterables

from qontract_api.gitlab.gitlab_client_factory import create_gitlab_workspace_client
from qontract_api.integrations.gitlab_projects.schemas import (
    GitlabProjectAction,
    GitlabProjectActionCreate,
    GitlabProjectActionCreateSaasBundle,
    GitlabProjectsTaskResult,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from qontract_api.cache import CacheBackend
    from qontract_api.config import Settings
    from qontract_api.gitlab.gitlab_workspace_client import GitlabWorkspaceClient
    from qontract_api.integrations.gitlab_projects.domain import (
        GitlabGroupConfig,
        GitlabInstanceConfig,
        GitlabProjectConfig,
    )
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


class GitlabProjectsService:
    """Service for reconciling GitLab projects.

    Uses Dependency Injection to keep the service decoupled from secret backends.
    Talks to Layer 2 GitlabWorkspaceClient — never calls Layer 1 GitlabApi directly.

    The client already validated every requested project against app-interface
    codeComponents before sending it here (ADR-002); this service never needs
    to know about codeComponents or apps.
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
        instance_name: str,
        group_name: str,
        desired_projects: list[GitlabProjectConfig],
        existing_project_names: list[str],
    ) -> list[GitlabProjectAction]:
        # Actions are desired projects whose name isn't already present in the
        # group. diff.delete (existing but not desired) is deliberately never
        # actioned - this integration never deletes projects.
        diff = diff_any_iterables(
            current=existing_project_names,
            desired=desired_projects,
            current_key=lambda name: name,
            desired_key=lambda project: project.name,
        )
        missing = sorted(diff.add.values(), key=lambda project: project.name)

        actions: list[GitlabProjectAction] = []
        for project_cfg in missing:
            if project_cfg.is_saas_bundle:
                actions.append(
                    GitlabProjectActionCreateSaasBundle(
                        instance=instance_name,
                        group=group_name,
                        project_name=project_cfg.name,
                    )
                )
            else:
                actions.append(
                    GitlabProjectActionCreate(
                        instance=instance_name,
                        group=group_name,
                        project_name=project_cfg.name,
                    )
                )
        return actions

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    def _apply_actions(
        self,
        client: GitlabWorkspaceClient,
        instance_name: str,
        group_id: int,
        actions: list[GitlabProjectAction],
    ) -> tuple[list[GitlabProjectAction], list[str]]:
        applied: list[GitlabProjectAction] = []
        errors: list[str] = []

        for action in actions:
            try:
                self._execute_action(client, group_id, action)
                applied.append(action)
            except Exception as e:
                error_msg = (
                    f"{instance_name}/{action.group}/{action.project_name}/"
                    f"{action.action_type}: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)
        return applied, errors

    @staticmethod
    def _execute_action(
        client: GitlabWorkspaceClient,
        group_id: int,
        action: GitlabProjectAction,
    ) -> None:
        match action:
            case GitlabProjectActionCreate():
                logger.info(
                    f"Creating project {action.instance}/{action.group}/{action.project_name}",
                    action_type=action.action_type,
                )
                client.create_project(action.group, group_id, action.project_name)

            case GitlabProjectActionCreateSaasBundle():
                logger.info(
                    f"Creating SaaS bundle project {action.instance}/{action.group}/{action.project_name}",
                    action_type=action.action_type,
                )
                project = client.create_project(
                    action.group, group_id, action.project_name
                )
                client.initiate_saas_bundle_repo(project.id)

    # ------------------------------------------------------------------
    # Per-group / per-instance reconciliation
    # ------------------------------------------------------------------

    def _reconcile_group(
        self,
        client: GitlabWorkspaceClient,
        instance_name: str,
        group_cfg: GitlabGroupConfig,
        *,
        dry_run: bool,
    ) -> tuple[list[GitlabProjectAction], list[GitlabProjectAction], list[str]]:
        group = client.get_group(group_cfg.group)
        actions = self._calculate_actions(
            instance_name, group_cfg.group, group_cfg.projects, group.project_names
        )
        if not dry_run:
            applied, errors = self._apply_actions(
                client, instance_name, group.id, actions
            )
        else:
            applied, errors = [], []
        return actions, applied, errors

    def _reconcile_instance(
        self,
        instance: GitlabInstanceConfig,
        *,
        dry_run: bool,
    ) -> tuple[list[GitlabProjectAction], list[GitlabProjectAction], list[str]]:
        all_actions: list[GitlabProjectAction] = []
        all_applied: list[GitlabProjectAction] = []
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
        instances: list[GitlabInstanceConfig],
        *,
        dry_run: bool = True,
    ) -> GitlabProjectsTaskResult:
        """Reconcile GitLab projects across all provided instances."""
        all_actions: list[GitlabProjectAction] = []
        all_applied: list[GitlabProjectAction] = []
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

        return GitlabProjectsTaskResult(
            status=TaskStatus.FAILED if all_errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=all_applied,
            applied_count=len(all_applied),
            errors=all_errors,
        )
