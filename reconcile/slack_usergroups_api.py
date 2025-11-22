"""Slack usergroups reconciliation via qontract-api.

This is a POC client-side integration that calls the qontract-api
instead of directly managing Slack usergroups.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Differences from reconcile/slack_usergroups.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side
- Business logic (reconciliation) happens server-side (qontract-api)
- Simplified: No PagerDuty, GitHub owners, clusters (POC scope)
"""

import logging
import os
import sys
from datetime import datetime
from typing import Any

from qontract_api_client.api.integrations.slack_usergroups import (
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResponse,
)
from qontract_api_client.api.integrations.slack_usergroups import (
    sync as reconcile_slack_usergroups,
)
from qontract_api_client.api.integrations.slack_usergroups_task_status import (
    SlackUsergroupsTaskResult,
)
from qontract_api_client.api.integrations.slack_usergroups_task_status import (
    sync as slack_usergroups_task_status,
)
from qontract_api_client.client import AuthenticatedClient
from qontract_api_client.models import HTTPValidationError
from qontract_api_client.models.slack_usergroup import SlackUsergroup
from qontract_api_client.models.slack_usergroup_config import SlackUsergroupConfig
from qontract_api_client.models.slack_workspace import SlackWorkspace
from qontract_api_client.models.task_status import TaskStatus

from reconcile.gql_definitions.slack_usergroups.permissions import (
    PermissionSlackUsergroupV1,
    ScheduleEntryV1,
)
from reconcile.gql_definitions.slack_usergroups.permissions import (
    query as permissions_query,
)
from reconcile.utils import gql
from reconcile.utils.datetime_util import ensure_utc, utc_now

QONTRACT_INTEGRATION = "slack-usergroups-api"
INTEGRATION_VERSION = "0.1.0"
DATE_FORMAT = "%Y-%m-%d %H:%M"


def get_permissions(query_func: Any) -> list[PermissionSlackUsergroupV1]:
    """Query permissions from App-Interface.

    Args:
        query_func: GraphQL query function

    Returns:
        List of Slack usergroup permissions
    """
    result = permissions_query(query_func=query_func)
    if not result.permissions:
        return []

    # Filter for PermissionSlackUsergroupV1 only
    return [p for p in result.permissions if isinstance(p, PermissionSlackUsergroupV1)]


def get_slack_usernames_from_schedule(
    schedule: list[ScheduleEntryV1],
) -> list[str]:
    """Return list of Slack usernames from active schedule entries.

    Only includes users from schedule entries that are currently active
    (now is between start and end time).

    Args:
        schedule: List of schedule entries with start/end times and users

    Returns:
        List of Slack usernames from active schedules
    """
    now = utc_now()
    all_slack_usernames: list[str] = []
    for entry in schedule:
        start = ensure_utc(datetime.strptime(entry.start, DATE_FORMAT))  # noqa: DTZ007
        end = ensure_utc(datetime.strptime(entry.end, DATE_FORMAT))  # noqa: DTZ007
        if start <= now <= end:
            all_slack_usernames.extend(u.org_username for u in entry.users)
    return all_slack_usernames


def build_desired_state(
    permissions: list[PermissionSlackUsergroupV1],
    desired_workspace_name: str | None = None,
    desired_usergroup_name: str | None = None,
) -> list[SlackWorkspace]:
    """Build desired state from permissions.

    This POC version includes:
    - Users from roles (org_username)
    - Users from schedule (active time-based on-call rotations)
    - managed_usergroups validation (SECURITY)

    Not included in POC (requires qontract-api integration per ADR-013):
    - PagerDuty schedules (external API)
    - GitHub repo owners (external API)
    - Cluster users

    Args:
        permissions: List of permissions from App-Interface
        desired_workspace_name: Optional filter for specific workspace
        desired_usergroup_name: Optional filter for specific usergroup

    Returns:
        List of SlackWorkspace objects (fully typed!)
    """
    # Build workspace dict first, then convert to list
    workspaces_dict: dict[str, SlackWorkspace] = {}

    for permission in permissions:
        if permission.skip or not permission.workspace.managed_usergroups:
            continue

        workspace_name = permission.workspace.name

        # Filter by workspace if specified
        if desired_workspace_name and workspace_name != desired_workspace_name:
            continue

        # Extract vault token path from workspace integrations (do this once per workspace)
        if workspace_name not in workspaces_dict:
            vault_token_path: str | None = None
            if permission.workspace.integrations:
                for integration in permission.workspace.integrations:
                    if integration.name in {"slack-usergroups", QONTRACT_INTEGRATION}:
                        vault_token_path = integration.token.path
                        break

            if not vault_token_path:
                logging.warning(
                    f"Workspace {workspace_name} has no slack-usergroups integration token, skipping all usergroups"
                )
                continue

            # Create workspace object
            workspaces_dict[workspace_name] = SlackWorkspace(
                name=workspace_name,
                vault_token_path=vault_token_path,
                usergroups=[],
                managed_usergroups=permission.workspace.managed_usergroups
                if not desired_usergroup_name
                else [desired_usergroup_name],
            )

        # Get usergroup handle
        usergroup_handle = permission.handle

        # Filter by usergroup if specified
        if desired_usergroup_name and usergroup_handle != desired_usergroup_name:
            continue

        # Validate usergroup is in managed_usergroups (SECURITY)
        if usergroup_handle not in permission.workspace.managed_usergroups:
            raise KeyError(
                f"[{permission.workspace.name}] usergroup {usergroup_handle} \
                    not in managed usergroups {permission.workspace.managed_usergroups}"
            )

        # Build user list (simplified - just users from roles, no PagerDuty/GitHub/clusters)
        users: list[str] = []
        if permission.roles:
            for role in permission.roles:
                if role.users:
                    users.extend([
                        user.org_username for user in role.users if user.org_username
                    ])

        # Add users from schedule (time-based on-call rotations)
        if permission.schedule:
            slack_usernames_schedule = get_slack_usernames_from_schedule(
                permission.schedule.schedule
            )
            users.extend(slack_usernames_schedule)

        # Create config and usergroup
        config = SlackUsergroupConfig(
            description=permission.description or "",
            users=users,
            channels=sorted(set(permission.channels or [])),
        )

        usergroup = SlackUsergroup(handle=usergroup_handle, config=config)

        # Add to workspace
        workspace = workspaces_dict[workspace_name]
        assert isinstance(workspace.usergroups, list)  # for mypy
        workspace.usergroups.append(usergroup)

    return list(workspaces_dict.values())


def reconcile(
    client: AuthenticatedClient, workspaces: list[SlackWorkspace], dry_run: bool = True
) -> SlackUsergroupsTaskResponse:
    """Call qontract-api to reconcile Slack usergroups.

    Args:
        client: Authenticated qontract-api client
        workspaces: List of Slack workspaces with usergroups
        dry_run: If True, only calculate actions without executing

    Returns:
        Response from qontract-api

    Raises:
        requests.HTTPError: If API call fails
    """
    request_data = SlackUsergroupsReconcileRequest(
        workspaces=workspaces, dry_run=dry_run
    )
    response = reconcile_slack_usergroups(client=client, body=request_data)

    if isinstance(response, HTTPValidationError):
        logging.error(f"Validation error from qontract-api: {response}")
        sys.exit(1)
    # TODO _parse_response darf kein None zurueckgeben!!! in template overrides fixen
    assert response is not None
    return response


def task_status(
    client: AuthenticatedClient, task_id: str, timeout: int
) -> SlackUsergroupsTaskResult:
    """Call qontract-api to retrieve task status for Slack usergroups reconciliation.

    Args:
        client: Authenticated qontract-api client
        workspaces: List of Slack workspaces with usergroups
        dry_run: If True, only calculate actions without executing

    Returns:
        Response from qontract-api

    Raises:
        requests.HTTPError: If API call fails
    """
    response = slack_usergroups_task_status(
        client=client, task_id=task_id, timeout=timeout
    )

    if isinstance(response, HTTPValidationError):
        logging.error(f"Validation error from qontract-api: {response}")
        sys.exit(1)
    # TODO _parse_response darf kein None zurueckgeben!!! in template overrides fixen
    assert response is not None
    return response


def run(
    dry_run: bool,
    workspace_name: str | None = None,
    usergroup_name: str | None = None,
) -> None:
    """Run the integration.

    Args:
        dry_run: If True, only calculate actions without executing
        workspace_name: Optional filter for specific workspace
        usergroup_name: Optional filter for specific usergroup
    """
    gqlapi = gql.get_api()
    permissions = get_permissions(query_func=gqlapi.query)

    workspaces = build_desired_state(
        permissions,
        desired_workspace_name=workspace_name,
        desired_usergroup_name=usergroup_name,
    )

    if not workspaces:
        logging.warning("No desired state found, nothing to reconcile")
        return

    # Get qontract-api configuration from environment
    api_url = os.environ.get("QONTRACT_API_URL", "http://localhost:8080")
    token = os.environ.get("QONTRACT_API_TOKEN")

    if not token:
        logging.error(
            "QONTRACT_API_TOKEN environment variable not set. "
            "Please provide a valid JWT token."
        )
        sys.exit(1)

    # Call qontract-api
    client = AuthenticatedClient(
        base_url=api_url,
        token=token,
        raise_on_unexpected_status=True,
    )

    task = reconcile(client, workspaces=workspaces, dry_run=dry_run)
    if dry_run:
        # wait for task completion and get the action list
        task_result = task_status(client, task_id=task.task_id, timeout=300)
        if task_result.status == TaskStatus.PENDING:
            logging.error("Task did not complete within the timeout period")
            sys.exit(1)

        if task_result.actions:
            logging.info("Proposed actions:")
            for action in task_result.actions or []:
                logging.info(action)

        if task_result.errors:
            logging.error(f"Errors encountered: {len(task_result.errors)}")
            for error in task_result.errors:
                logging.error(f"  - {error}")
            sys.exit(1)
