import logging
import sys
from dataclasses import dataclass

from reconcile.gql_definitions.quay_robot_accounts.quay_robot_accounts import (
    QuayRobotV1,
    query,
)
from reconcile.quay_base import QuayApiStore, get_quay_api_store
from reconcile.status import ExitCodes
from reconcile.utils import gql
from reconcile.utils.quay_api import RobotAccountDetails

QONTRACT_INTEGRATION = "quay-robot-accounts"


@dataclass
class RobotAccountState:
    """Represents the state of a robot account"""

    name: str
    description: str | None
    org_name: str
    instance_name: str
    teams: set[str]
    repositories: dict[str, str]  # repo_name -> permission


@dataclass
class RobotAccountAction:
    """Represents an action to be performed on a robot account"""

    action: str  # 'create', 'delete', 'add_team', 'remove_team', 'set_repo_permission', 'remove_repo_permission'
    robot_name: str
    org_name: str
    instance_name: str
    team: str | None = None
    repo: str | None = None
    permission: str | None = None


def get_robot_accounts_from_gql() -> list[QuayRobotV1]:
    """Fetch robot account definitions from GraphQL"""
    query_data = query(query_func=gql.get_api().query)
    return list(query_data.robot_accounts or [])


def get_current_robot_accounts(
    quay_api_store: QuayApiStore,
) -> dict[tuple[str, str], list[RobotAccountDetails]]:
    """Fetch current robot accounts from Quay API for all organizations"""
    current_state = {}

    for org_key, org_info in quay_api_store.items():
        try:
            robots = org_info["api"].list_robot_accounts()
            current_state[org_key.instance, org_key.org_name] = robots or []
        except Exception as e:
            logging.error(
                f"Failed to fetch robot accounts for {org_key.instance}/{org_key.org_name}: {e}"
            )
            current_state[org_key.instance, org_key.org_name] = []

    return current_state


def build_desired_state(
    robot_accounts: list[QuayRobotV1],
) -> dict[tuple[str, str, str], RobotAccountState]:
    """Build desired state from GraphQL definitions"""
    desired_state = {}

    for robot in robot_accounts:
        if not robot.quay_org:
            continue

        instance_name = robot.quay_org.instance.name
        org_name = robot.quay_org.name
        robot_name = robot.name

        teams = set(robot.teams or [])
        repositories = {}

        if robot.repositories:
            for repo in robot.repositories:
                repositories[repo.name] = repo.permission

        state = RobotAccountState(
            name=robot_name,
            description=robot.description,
            org_name=org_name,
            instance_name=instance_name,
            teams=teams,
            repositories=repositories,
        )

        desired_state[instance_name, org_name, robot_name] = state

    return desired_state


def build_current_state(
    current_robots: dict[tuple[str, str], list[RobotAccountDetails]],
    quay_api_store: QuayApiStore,
) -> dict[tuple[str, str, str], RobotAccountState]:
    """Build current state from Quay API data"""
    current_state = {}

    for (instance_name, org_name), robots in current_robots.items():
        org_key = next(
            (
                k
                for k in quay_api_store
                if k.instance == instance_name and k.org_name == org_name
            ),
            None,
        )

        if not org_key:
            continue

        for robot_data in robots:
            robot_name = robot_data["name"]
            description = robot_data.get("description")

            # Get team memberships
            teams: set[str] = set()
            team_permissions = robot_data.get("teams", [])
            teams.update(team_perm["name"] for team_perm in team_permissions)

            # Get repository permissions
            repositories = {}
            repo_permissions = robot_data.get("repositories", [])
            for repo_perm in repo_permissions:
                repositories[repo_perm["name"]] = repo_perm["role"]

            state = RobotAccountState(
                name=robot_name,
                description=description,
                org_name=org_name,
                instance_name=instance_name,
                teams=teams,
                repositories=repositories,
            )

            current_state[instance_name, org_name, robot_name] = state

    return current_state


def calculate_diff(
    desired_state: dict[tuple[str, str, str], RobotAccountState],
    current_state: dict[tuple[str, str, str], RobotAccountState],
) -> list[RobotAccountAction]:
    """Calculate the differences between desired and current state"""
    actions = []

    # Find robots to create
    for key, desired in desired_state.items():
        if key not in current_state:
            actions.append(
                RobotAccountAction(
                    action="create",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                )
            )

            # Add team assignments for new robot
            actions.extend([
                RobotAccountAction(
                    action="add_team",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    team=team,
                )
                for team in desired.teams
            ])

            # Add repository permissions for new robot
            actions.extend([
                RobotAccountAction(
                    action="set_repo_permission",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    repo=repo,
                    permission=permission,
                )
                for repo, permission in desired.repositories.items()
            ])
        else:
            current = current_state[key]

            # Check team differences
            teams_to_add = desired.teams - current.teams
            teams_to_remove = current.teams - desired.teams

            actions.extend([
                RobotAccountAction(
                    action="add_team",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    team=team,
                )
                for team in teams_to_add
            ])

            actions.extend([
                RobotAccountAction(
                    action="remove_team",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    team=team,
                )
                for team in teams_to_remove
            ])

            # Check repository permission differences
            desired_repos = set(desired.repositories.keys())
            current_repos = set(current.repositories.keys())

            # Repositories to add or update permissions
            actions.extend(
                RobotAccountAction(
                    action="set_repo_permission",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    repo=repo,
                    permission=desired.repositories[repo],
                )
                for repo in desired_repos
                if repo not in current_repos
                or desired.repositories[repo] != current.repositories.get(repo)
            )

            # Repositories to remove permissions from
            repos_to_remove = current_repos - desired_repos
            actions.extend([
                RobotAccountAction(
                    action="remove_repo_permission",
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    repo=repo,
                )
                for repo in repos_to_remove
            ])

    # Find robots to delete (robots in current state but not in desired state)
    for key, current in current_state.items():
        if key not in desired_state:
            actions.append(
                RobotAccountAction(
                    action="delete",
                    robot_name=current.name,
                    org_name=current.org_name,
                    instance_name=current.instance_name,
                )
            )

    return actions


def apply_action(
    action: RobotAccountAction,
    quay_api_store: QuayApiStore,
    dry_run: bool = False,
) -> None:
    """Apply a single action to Quay"""
    org_key = next(
        (
            k
            for k in quay_api_store
            if k.instance == action.instance_name and k.org_name == action.org_name
        ),
        None,
    )

    if not org_key:
        logging.error(f"No API found for {action.instance_name}/{action.org_name}")
        return

    quay_api = quay_api_store[org_key]["api"]

    if dry_run:
        logging.info(f"[DRY RUN] Would perform: {action}")
        return

    try:
        if action.action == "create":
            logging.info(
                f"Creating robot account {action.robot_name} in {action.org_name}"
            )
            quay_api.create_robot_account(action.robot_name, "")

        elif action.action == "delete":
            logging.info(
                f"Deleting robot account {action.robot_name} from {action.org_name}"
            )
            quay_api.delete_robot_account(action.robot_name)

        elif action.action == "add_team":
            logging.info(
                f"Adding robot {action.robot_name} to team {action.team} in {action.org_name}"
            )
            if not action.team:
                raise ValueError(f"Team is required for add_team action: {action}")
            quay_api.add_user_to_team(
                f"{action.org_name}+{action.robot_name}", action.team
            )

        elif action.action == "remove_team":
            logging.info(
                f"Removing robot {action.robot_name} from team {action.team} in {action.org_name}"
            )
            if not action.team:
                raise ValueError(f"Team is required for remove_team action: {action}")
            quay_api.remove_user_from_team(
                f"{action.org_name}+{action.robot_name}", action.team
            )

        elif action.action == "set_repo_permission":
            logging.info(
                f"Setting {action.permission} permission for robot {action.robot_name} on repo {action.repo}"
            )
            if not action.repo:
                raise ValueError(
                    f"Repo is required for set_repo_permission action: {action}"
                )
            if not action.permission:
                raise ValueError(
                    f"Permission is required for set_repo_permission action: {action}"
                )
            quay_api.set_repo_robot_account_permissions(
                action.repo, action.robot_name, action.permission
            )

        elif action.action == "remove_repo_permission":
            logging.info(
                f"Removing permissions for robot {action.robot_name} from repo {action.repo}"
            )
            if not action.repo:
                raise ValueError(
                    f"Repo is required for set_repo_permissions action: {action}"
                )
            quay_api.delete_repo_robot_account_permissions(
                action.repo, action.robot_name
            )

    except Exception as e:
        logging.error(f"Failed to apply action {action}: {e}")
        raise


def run(dry_run: bool = False) -> None:
    """Main function to run the integration"""
    try:
        # Get GraphQL data
        robot_accounts = get_robot_accounts_from_gql()
        logging.info(f"Found {len(robot_accounts)} robot account definitions")

        # Get Quay API store
        quay_api_store = get_quay_api_store()

        # Get current state from Quay
        current_robots = get_current_robot_accounts(quay_api_store)

        # Build states
        desired_state = build_desired_state(robot_accounts)
        current_state = build_current_state(current_robots, quay_api_store)

        logging.info(f"Desired robots: {len(desired_state)}")
        logging.info(f"Current robots: {len(current_state)}")

        # Calculate diff
        actions = calculate_diff(desired_state, current_state)

        if not actions:
            logging.info("No actions needed")
            return

        logging.info(f"Found {len(actions)} actions to perform")

        if dry_run:
            logging.info("Running in dry-run mode - no changes will be made")

        # Apply actions
        for action in actions:
            apply_action(action, quay_api_store, dry_run)

        logging.info("Integration completed successfully")

    except Exception as e:
        logging.error(f"Integration failed: {e}")
        sys.exit(ExitCodes.ERROR)
