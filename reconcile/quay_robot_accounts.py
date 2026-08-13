from __future__ import annotations

import logging
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from qontract_utils.differ import diff_mappings

from reconcile.gql_definitions.quay_robot_accounts.quay_robot_accounts import (
    QuayRobotV1,
    query,
)
from reconcile.quay_base import OrgKey, QuayApiStore, get_quay_api_store
from reconcile.status import ExitCodes
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Iterable

    from reconcile.utils.quay_api import RobotAccountDetails

QONTRACT_INTEGRATION = "quay-robot-accounts"


class RobotAccountActionType(Enum):
    CREATE = "create"
    DELETE = "delete"
    ADD_TEAM = "add_team"
    REMOVE_TEAM = "remove_team"
    SET_REPO_PERMISSION = "set_repo_permission"
    REMOVE_REPO_PERMISSION = "remove_repo_permission"


@dataclass
class RobotAccountState:
    """Represents the state of a robot account"""

    name: str
    description: str | None
    org_name: str
    instance_name: str
    teams: set[str]
    repositories: dict[str, str]  # repo_name -> permission
    delete: bool = False


@dataclass
class RobotAccountAction:
    """Represents an action to be performed on a robot account"""

    action: RobotAccountActionType
    robot_name: str
    org_name: str
    instance_name: str
    team: str | None = None
    repo: str | None = None
    permission: str | None = None
    description: str | None = None


def get_robot_accounts_from_gql() -> list[QuayRobotV1]:
    """Fetch robot account definitions from GraphQL"""
    query_data = query(query_func=gql.get_api().query)
    return list(query_data.robot_accounts or [])


def desired_org_keys(
    desired_state: dict[tuple[str, str, str], RobotAccountState],
) -> set[OrgKey]:
    """Org keys referenced by desired robot definitions."""
    return {
        OrgKey(state.instance_name, state.org_name) for state in desired_state.values()
    }


def get_current_robot_accounts(
    quay_api_store: QuayApiStore,
    org_keys: Iterable[OrgKey],
) -> dict[tuple[str, str], list[RobotAccountDetails]]:
    """Fetch current robot accounts from Quay for the given organizations.

    Only opted-in orgs that appear in desired state should be passed here.
    Auth failures (and other API errors) propagate — callers must fail closed.
    """
    current_state: dict[tuple[str, str], list[RobotAccountDetails]] = {}

    for org_key in org_keys:
        org_info = quay_api_store[org_key]
        robots = org_info["api"].list_robot_accounts()
        current_state[org_key.instance, org_key.org_name] = robots or []

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
            delete=robot.delete or False,
        )

        desired_state[instance_name, org_name, robot_name] = state

    return desired_state


def build_current_state(
    current_robots: dict[tuple[str, str], list[RobotAccountDetails]],
    quay_api_store: QuayApiStore,
    desired_keys: set[tuple[str, str, str]],
) -> dict[tuple[str, str, str], RobotAccountState]:
    """Build current state from Quay API data for desired robots only.

    Unmanaged robots (present in Quay but not in desired state) are ignored —
    calculate_diff never deletes them without delete: true. Only managedTeams
    memberships are tracked, and repository permissions only when managedRepos
    is true. Auth failures on permission lookups propagate.
    """
    current_state = {}

    for (instance_name, org_name), robots in current_robots.items():
        org_key = OrgKey(instance_name, org_name)
        if org_key not in quay_api_store:
            continue

        org_info = quay_api_store[org_key]
        quay_api = org_info["api"]
        managed_teams = set(org_info["teams"] or [])

        for robot_data in robots:
            robot_name = robot_data["name"]  # already normalized to short name
            key = (instance_name, org_name, robot_name)
            if key not in desired_keys:
                continue

            description = robot_data.get("description")

            # Only reconcile membership for teams declared as managedTeams
            teams = set(robot_data.get("teams", [])) & managed_teams

            # Get repository permissions via dedicated endpoint (the robots list
            # endpoint only returns repo names, not roles). Skip when the org
            # does not manage repos (same gate as quay-permissions / quay-repos).
            repositories: dict[str, str] = {}
            if org_info["managedRepos"]:
                permissions = quay_api.get_robot_account_permissions(robot_name)
                for perm in permissions:
                    repositories[perm["repository"]["name"]] = perm["role"]

            state = RobotAccountState(
                name=robot_name,
                description=description,
                org_name=org_name,
                instance_name=instance_name,
                teams=teams,
                repositories=repositories,
            )

            current_state[key] = state

    return current_state


def validate_desired_state(
    desired_state: dict[tuple[str, str, str], RobotAccountState],
    quay_api_store: QuayApiStore,
) -> bool:
    """Validate desired state against Quay org guardrails.

    Mirrors quay-membership (managedTeams) and quay-permissions (managedRepos):
    - org must have an automation token / API client in the store
    - org must opt in via managedRobotAccounts=true
    - every desired team must be listed in the org's managedTeams
    - repository permissions require managedRepos=true on the org

    Returns True when valid; logs errors and returns False otherwise.
    """
    valid = True

    for desired in desired_state.values():
        org_key = OrgKey(desired.instance_name, desired.org_name)
        if org_key not in quay_api_store:
            logging.error(
                f"No API found for {desired.instance_name}/{desired.org_name} "
                f"(robot {desired.name}). Ensure the org has an automationToken."
            )
            valid = False
            continue

        org_info = quay_api_store[org_key]
        if not org_info["managedRobotAccounts"]:
            logging.error(
                f"Can not manage robot {desired.name} in "
                f"{desired.instance_name}/{desired.org_name} since "
                f"managedRobotAccounts is not set to true."
            )
            valid = False
            continue

        if desired.delete:
            continue

        managed_teams = set(org_info["teams"] or [])

        for team in desired.teams:
            if team not in managed_teams:
                logging.error(
                    f"Quay team {team} is not defined as a managedTeam "
                    f"in the {org_key.org_name} org (robot {desired.name})."
                )
                valid = False

        if desired.repositories and not org_info["managedRepos"]:
            logging.error(
                f"Can not manage repo permissions for robot {desired.name} in "
                f"{org_key.org_name} since managedRepos is set to false."
            )
            valid = False

    return valid


def calculate_diff(
    desired_state: dict[tuple[str, str, str], RobotAccountState],
    current_state: dict[tuple[str, str, str], RobotAccountState],
) -> list[RobotAccountAction]:
    """Calculate the differences between desired and current state"""
    actions = []

    for key, desired in desired_state.items():
        if desired.delete:
            # Explicit deletion requested — delete if it exists, no-op otherwise
            if key in current_state:
                actions.append(
                    RobotAccountAction(
                        action=RobotAccountActionType.DELETE,
                        robot_name=desired.name,
                        org_name=desired.org_name,
                        instance_name=desired.instance_name,
                    )
                )
            continue

        if key not in current_state:
            actions.append(
                RobotAccountAction(
                    action=RobotAccountActionType.CREATE,
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    description=desired.description,
                )
            )

            # Add team assignments for new robot
            actions.extend([
                RobotAccountAction(
                    action=RobotAccountActionType.ADD_TEAM,
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
                    action=RobotAccountActionType.SET_REPO_PERMISSION,
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
                    action=RobotAccountActionType.ADD_TEAM,
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    team=team,
                )
                for team in teams_to_add
            ])

            actions.extend([
                RobotAccountAction(
                    action=RobotAccountActionType.REMOVE_TEAM,
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    team=team,
                )
                for team in teams_to_remove
            ])

            # Check repository permission differences
            repo_diff = diff_mappings(current.repositories, desired.repositories)

            for repo, role in repo_diff.add.items():
                actions.append(
                    RobotAccountAction(
                        action=RobotAccountActionType.SET_REPO_PERMISSION,
                        robot_name=desired.name,
                        org_name=desired.org_name,
                        instance_name=desired.instance_name,
                        repo=repo,
                        permission=role,
                    )
                )

            for repo, pair in repo_diff.change.items():
                actions.append(
                    RobotAccountAction(
                        action=RobotAccountActionType.SET_REPO_PERMISSION,
                        robot_name=desired.name,
                        org_name=desired.org_name,
                        instance_name=desired.instance_name,
                        repo=repo,
                        permission=pair.desired,
                    )
                )

            actions.extend(
                RobotAccountAction(
                    action=RobotAccountActionType.REMOVE_REPO_PERMISSION,
                    robot_name=desired.name,
                    org_name=desired.org_name,
                    instance_name=desired.instance_name,
                    repo=repo,
                )
                for repo in repo_diff.delete
            )

    # Robots in current state but not in desired state are intentionally ignored —
    # they may be managed outside of app-interface. Use delete: true to explicitly
    # remove a robot account.

    return actions


def apply_action(
    action: RobotAccountAction,
    quay_api_store: QuayApiStore,
    dry_run: bool = False,
) -> bool:
    """Apply a single action to Quay.

    Returns True on success. Returns False (and logs) when the org API client
    is missing so callers can fail closed without silently skipping work.
    """
    org_key = OrgKey(action.instance_name, action.org_name)
    if org_key not in quay_api_store:
        logging.error(f"No API found for {action.instance_name}/{action.org_name}")
        return False

    quay_api = quay_api_store[org_key]["api"]

    match action.action:
        case RobotAccountActionType.CREATE:
            logging.info(
                f"Creating robot account {action.robot_name} in {action.org_name}"
            )
            if not dry_run:
                quay_api.create_robot_account(
                    action.robot_name, action.description or ""
                )

        case RobotAccountActionType.DELETE:
            logging.info(
                f"Deleting robot account {action.robot_name} from {action.org_name}"
            )
            if not dry_run:
                quay_api.delete_robot_account(action.robot_name)

        case RobotAccountActionType.ADD_TEAM:
            if not action.team:
                raise ValueError(f"Team is required for add_team action: {action}")
            logging.info(
                f"Adding robot {action.robot_name} to team {action.team} in {action.org_name}"
            )
            if not dry_run:
                quay_api.add_user_to_team(
                    f"{action.org_name}+{action.robot_name}", action.team
                )

        case RobotAccountActionType.REMOVE_TEAM:
            if not action.team:
                raise ValueError(f"Team is required for remove_team action: {action}")
            logging.info(
                f"Removing robot {action.robot_name} from team {action.team} in {action.org_name}"
            )
            if not dry_run:
                quay_api.remove_robot_from_team(action.robot_name, action.team)

        case RobotAccountActionType.SET_REPO_PERMISSION:
            if not action.repo:
                raise ValueError(
                    f"Repo is required for set_repo_permission action: {action}"
                )
            if not action.permission:
                raise ValueError(
                    f"Permission is required for set_repo_permission action: {action}"
                )
            logging.info(
                f"Setting {action.permission} permission for robot {action.robot_name} on repo {action.repo}"
            )
            if not dry_run:
                quay_api.set_repo_robot_account_permissions(
                    action.repo, action.robot_name, action.permission
                )

        case RobotAccountActionType.REMOVE_REPO_PERMISSION:
            if not action.repo:
                raise ValueError(
                    f"Repo is required for remove_repo_permission action: {action}"
                )
            logging.info(
                f"Removing permissions for robot {action.robot_name} from repo {action.repo}"
            )
            if not dry_run:
                quay_api.delete_repo_robot_account_permissions(
                    action.repo, action.robot_name
                )

    return True


def run(dry_run: bool = False) -> None:
    """Main function to run the integration"""
    robot_accounts = get_robot_accounts_from_gql()
    logging.debug(f"Found {len(robot_accounts)} robot account definitions")

    error = False

    with get_quay_api_store() as quay_api_store:
        desired_state = build_desired_state(robot_accounts)

        if not validate_desired_state(desired_state, quay_api_store):
            sys.exit(ExitCodes.ERROR)

        # Inventory only orgs that have desired robots and opted in. Validation
        # already ensured managedRobotAccounts=true for every desired org.
        org_keys = desired_org_keys(desired_state)
        current_robots = get_current_robot_accounts(quay_api_store, org_keys)
        current_state = build_current_state(
            current_robots, quay_api_store, set(desired_state)
        )

        logging.debug(f"Desired robots: {len(desired_state)}")
        logging.debug(f"Current robots: {len(current_state)}")

        actions = calculate_diff(desired_state, current_state)

        if not actions:
            logging.debug("No actions needed")
            return

        logging.debug(f"Found {len(actions)} actions to perform")

        if dry_run:
            logging.debug("Running in dry-run mode - no changes will be made")

        for action in actions:
            try:
                if not apply_action(action, quay_api_store, dry_run):
                    error = True
            except Exception:
                logging.exception(
                    "Failed to apply action %s for robot %s in %s/%s",
                    action.action.value,
                    action.robot_name,
                    action.instance_name,
                    action.org_name,
                )
                error = True

    if error:
        sys.exit(ExitCodes.ERROR)

    logging.debug("Integration completed successfully")
