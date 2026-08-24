"""Quay robot-accounts reconciliation service."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from qontract_utils.differ import diff_iterables, diff_mappings

from qontract_api.integrations.quay_robot_accounts.schemas import (
    QuayRobotAccountsTaskResult,
    QuayRobotAction,
    QuayRobotActionAddTeam,
    QuayRobotActionCreate,
    QuayRobotActionDelete,
    QuayRobotActionRemoveRepoPermission,
    QuayRobotActionRemoveTeam,
    QuayRobotActionSetRepoPermission,
)
from qontract_api.logger import get_logger
from qontract_api.models import TaskStatus

if TYPE_CHECKING:
    from qontract_api.config import Settings
    from qontract_api.integrations.quay_robot_accounts.domain import (
        QuayOrgDesiredState,
        QuayRobotDesiredState,
    )
    from qontract_api.quay import QuayClientFactory, QuayWorkspaceClient
    from qontract_api.secret_manager import SecretManager

logger = get_logger(__name__)


@dataclass(frozen=True)
class _CurrentRobot:
    name: str
    teams: set[str] = field(default_factory=set)
    repositories: dict[str, str] = field(default_factory=dict)


class QuayRobotAccountsService:
    """Service for reconciling Quay robot accounts.

    Per-org error isolation: one failed organization does not abort the rest.
    Unmanaged robots (present in Quay but not in desired state) are ignored.
    Deletion requires an explicit delete flag on the desired robot.
    """

    def __init__(
        self,
        quay_client_factory: QuayClientFactory,
        secret_manager: SecretManager,
        settings: Settings,
    ) -> None:
        self.quay_client_factory = quay_client_factory
        self.secret_manager = secret_manager
        self.settings = settings

    def _create_quay_client(self, org: QuayOrgDesiredState) -> QuayWorkspaceClient:
        token = self.secret_manager.read(org.token)
        return self.quay_client_factory.create_workspace_client(
            instance_name=org.instance_name,
            organization=org.org_name,
            token=token,
            base_url=org.instance_url,
        )

    @staticmethod
    def _validate_org(org: QuayOrgDesiredState) -> list[str]:
        """Return validation errors for an org. Empty list means valid."""
        errors: list[str] = []
        org_label = f"{org.instance_name}/{org.org_name}"

        if not org.managed_robot_accounts:
            errors.append(
                f"{org_label}: cannot manage robot accounts because "
                "managedRobotAccounts is not set to true"
            )
            return errors

        managed_teams = set(org.managed_teams)
        for robot in org.robots:
            if robot.delete:
                continue
            errors.extend(
                f"{org_label}: Quay team {team} is not defined as a "
                f"managedTeam (robot {robot.name})"
                for team in robot.teams
                if team not in managed_teams
            )
            if robot.repositories and not org.managed_repos:
                errors.append(
                    f"{org_label}: cannot manage repo permissions for robot "
                    f"{robot.name} because managedRepos is set to false"
                )
        return errors

    @staticmethod
    def _current_robots(
        org: QuayOrgDesiredState,
        quay_client: QuayWorkspaceClient,
    ) -> dict[str, _CurrentRobot]:
        """Inventory current state for desired robots only."""
        desired_names = {robot.name for robot in org.robots}
        managed_teams = set(org.managed_teams)
        current: dict[str, _CurrentRobot] = {}

        for robot in quay_client.list_robot_accounts():
            if robot.name not in desired_names:
                continue
            repositories: dict[str, str] = {}
            if org.managed_repos:
                permissions = quay_client.get_robot_account_permissions(robot.name)
                repositories = {perm.repository.name: perm.role for perm in permissions}
            current[robot.name] = _CurrentRobot(
                name=robot.name,
                teams=set(robot.teams) & managed_teams,
                repositories=repositories,
            )
        return current

    @staticmethod
    def _actions_for_robot(
        org: QuayOrgDesiredState,
        desired: QuayRobotDesiredState,
        current: _CurrentRobot | None,
    ) -> list[QuayRobotAction]:
        instance_name = org.instance_name
        org_name = org.org_name
        robot_name = desired.name

        if desired.delete:
            if current is None:
                return []
            return [
                QuayRobotActionDelete(
                    instance_name=instance_name,
                    org_name=org_name,
                    robot_name=robot_name,
                )
            ]

        actions: list[QuayRobotAction] = []
        if current is None:
            actions.append(
                QuayRobotActionCreate(
                    instance_name=instance_name,
                    org_name=org_name,
                    robot_name=robot_name,
                    description=desired.description,
                )
            )
            current_teams: set[str] = set()
            current_repos: dict[str, str] = {}
        else:
            current_teams = current.teams
            current_repos = current.repositories

        team_diff = diff_iterables(current_teams, desired.teams, key=lambda team: team)
        actions.extend(
            QuayRobotActionAddTeam(
                instance_name=instance_name,
                org_name=org_name,
                robot_name=robot_name,
                team=team,
            )
            for team in team_diff.add
        )
        actions.extend(
            QuayRobotActionRemoveTeam(
                instance_name=instance_name,
                org_name=org_name,
                robot_name=robot_name,
                team=team,
            )
            for team in team_diff.delete
        )

        repo_diff = diff_mappings(current_repos, desired.repositories)
        for repo, role in repo_diff.add.items():
            actions.append(
                QuayRobotActionSetRepoPermission(
                    instance_name=instance_name,
                    org_name=org_name,
                    robot_name=robot_name,
                    repo=repo,
                    permission=role,
                )
            )
        for repo, pair in repo_diff.change.items():
            actions.append(
                QuayRobotActionSetRepoPermission(
                    instance_name=instance_name,
                    org_name=org_name,
                    robot_name=robot_name,
                    repo=repo,
                    permission=pair.desired,
                )
            )
        actions.extend(
            QuayRobotActionRemoveRepoPermission(
                instance_name=instance_name,
                org_name=org_name,
                robot_name=robot_name,
                repo=repo,
            )
            for repo in repo_diff.delete
        )
        return actions

    def _calculate_actions(
        self,
        org: QuayOrgDesiredState,
        quay_client: QuayWorkspaceClient,
    ) -> list[QuayRobotAction]:
        current = self._current_robots(org, quay_client)
        actions: list[QuayRobotAction] = []
        for desired in org.robots:
            actions.extend(
                self._actions_for_robot(org, desired, current.get(desired.name))
            )
        return actions

    @staticmethod
    def _execute_action(
        quay_client: QuayWorkspaceClient,
        action: QuayRobotAction,
    ) -> None:
        match action:
            case QuayRobotActionCreate():
                logger.info(
                    f"Creating robot account {action.robot_name} in {action.org_name}"
                )
                quay_client.create_robot_account(
                    action.robot_name, action.description or ""
                )
            case QuayRobotActionDelete():
                logger.info(
                    f"Deleting robot account {action.robot_name} from {action.org_name}"
                )
                quay_client.delete_robot_account(action.robot_name)
            case QuayRobotActionAddTeam():
                logger.info(
                    f"Adding robot {action.robot_name} to team {action.team} "
                    f"in {action.org_name}"
                )
                quay_client.add_robot_to_team(action.robot_name, action.team)
            case QuayRobotActionRemoveTeam():
                logger.info(
                    f"Removing robot {action.robot_name} from team {action.team} "
                    f"in {action.org_name}"
                )
                quay_client.remove_robot_from_team(action.robot_name, action.team)
            case QuayRobotActionSetRepoPermission():
                logger.info(
                    f"Setting {action.permission} permission for robot "
                    f"{action.robot_name} on repo {action.repo}"
                )
                quay_client.set_repo_robot_account_permissions(
                    action.repo, action.robot_name, action.permission
                )
            case QuayRobotActionRemoveRepoPermission():
                logger.info(
                    f"Removing permissions for robot {action.robot_name} "
                    f"from repo {action.repo}"
                )
                quay_client.delete_repo_robot_account_permissions(
                    action.repo, action.robot_name
                )

    def reconcile(
        self,
        organizations: list[QuayOrgDesiredState],
        *,
        dry_run: bool = True,
    ) -> QuayRobotAccountsTaskResult:
        """Reconcile Quay robot accounts for the given organizations."""
        all_actions: list[QuayRobotAction] = []
        applied_actions: list[QuayRobotAction] = []
        errors: list[str] = []

        for org in organizations:
            org_label = f"{org.instance_name}/{org.org_name}"
            logger.info(f"Reconciling Quay org: {org_label}")

            if validation_errors := self._validate_org(org):
                errors.extend(validation_errors)
                continue

            try:
                quay_client = self._create_quay_client(org)
                org_actions = self._calculate_actions(org, quay_client)
                all_actions.extend(org_actions)
            except Exception as e:
                error_msg = (
                    f"{org_label}: Unexpected error during diff calculation: {e}"
                )
                logger.exception(error_msg)
                errors.append(error_msg)
                continue

            if not dry_run and org_actions:
                for action in org_actions:
                    try:
                        self._execute_action(quay_client, action)
                        applied_actions.append(action)
                    except Exception as e:
                        error_msg = (
                            f"{action.instance_name}/{action.org_name}/"
                            f"{action.robot_name}: Failed to execute "
                            f"{action.action_type}: {e}"
                        )
                        logger.exception(error_msg)
                        errors.append(error_msg)

        return QuayRobotAccountsTaskResult(
            status=TaskStatus.FAILED if errors else TaskStatus.SUCCESS,
            actions=all_actions,
            applied_actions=applied_actions,
            applied_count=len(applied_actions),
            errors=errors,
        )
