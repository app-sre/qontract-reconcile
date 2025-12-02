"""Slack usergroups reconciliation via qontract-api.

This is a POC client-side integration that calls the qontract-api
instead of directly managing Slack usergroups.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Differences from reconcile/slack_usergroups.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side
- Business logic (reconciliation) happens server-side (qontract-api)
"""

import asyncio
import logging
import sys
from collections import defaultdict
from collections.abc import Callable, Coroutine, Iterable, Mapping
from datetime import datetime
from typing import Any

from pydantic import BaseModel
from qontract_api_client.api.external.pagerduty_escalation_policy_users import (
    EscalationPolicyUsersResponse,
)
from qontract_api_client.api.external.pagerduty_escalation_policy_users import (
    asyncio as get_pagerduty_escalation_policy_users,
)
from qontract_api_client.api.external.pagerduty_schedule_users import (
    ScheduleUsersResponse,
)
from qontract_api_client.api.external.pagerduty_schedule_users import (
    asyncio as get_pagerduty_schedule_users,
)
from qontract_api_client.api.external.vcs_repo_owners import (
    RepoOwnersResponse,
)
from qontract_api_client.api.external.vcs_repo_owners import (
    asyncio as get_repo_owners,
)
from qontract_api_client.api.integrations.slack_usergroups import (
    SlackUsergroupsReconcileRequest,
    SlackUsergroupsTaskResponse,
)
from qontract_api_client.api.integrations.slack_usergroups import (
    asyncio as reconcile_slack_usergroups,
)
from qontract_api_client.api.integrations.slack_usergroups_task_status import (
    asyncio as slack_usergroups_task_status,
)
from qontract_api_client.models import (
    SlackUsergroupActionUpdateUsers,
)
from qontract_api_client.models.slack_usergroup import SlackUsergroup
from qontract_api_client.models.slack_usergroup_config import SlackUsergroupConfig
from qontract_api_client.models.slack_workspace import (
    SlackWorkspace as SlackWorkspaceRequest,
)
from qontract_api_client.models.task_status import TaskStatus
from qontract_api_client.models.vcs_provider import VCSProvider

from reconcile.gql_definitions.slack_usergroups.clusters import ClusterV1
from reconcile.gql_definitions.slack_usergroups.clusters import query as clusters_query
from reconcile.gql_definitions.slack_usergroups.permissions import (
    PagerDutyTargetV1,
    PermissionSlackUsergroupV1,
    RoleV1,
    ScheduleV1,
)
from reconcile.gql_definitions.slack_usergroups.permissions import (
    query as permissions_query,
)
from reconcile.gql_definitions.slack_usergroups.roles import RoleV1 as ClusterAccessRole
from reconcile.gql_definitions.slack_usergroups.roles import UserV1 as ClusterAccessUser
from reconcile.gql_definitions.slack_usergroups.roles import query as roles_query
from reconcile.gql_definitions.slack_usergroups.users import UserV1
from reconcile.gql_definitions.slack_usergroups.users import query as users_query
from reconcile.utils import expiration, gql
from reconcile.utils.datetime_util import ensure_utc, utc_now
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "slack-usergroups-api"
INTEGRATION_VERSION = "0.1.0"
DATE_FORMAT = "%Y-%m-%d %H:%M"


class SlackWorkspace(BaseModel, arbitrary_types_allowed=True):
    """A Slack workspace with its token and usergroups."""

    name: str
    usergroups: list[SlackUsergroup]
    managed_usergroups: list[str]
    default_channel: str


class SlackUsergroupsIntegrationParams(PydanticRunParams):
    """Parameters for slack-usergroups-api integration."""

    workspace_name: str | None
    usergroup_name: str | None


class SlackUsergroupsIntegration(
    QontractReconcileApiIntegration[SlackUsergroupsIntegrationParams]
):
    """Manage Slack usergroups via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
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

        # Filter for PermissionSlackUsergroupV1 to make mypy happy
        return [
            p for p in result.permissions if isinstance(p, PermissionSlackUsergroupV1)
        ]

    @staticmethod
    def get_users(query_func: Callable) -> list[UserV1]:
        """Return all users from app-interface."""
        return users_query(query_func=query_func).users or []

    @staticmethod
    def get_clusters(query_func: Callable) -> list[ClusterV1]:
        """Return all clusters from app-interface."""
        return [
            cluster
            for cluster in clusters_query(query_func=query_func).clusters or []
            if integration_is_enabled(QONTRACT_INTEGRATION, cluster)
            and integration_is_enabled("slack-usergroups", cluster)
        ]

    @staticmethod
    def get_roles(query_func: Callable) -> list[ClusterAccessRole]:
        """Return all roles from app-interface."""
        roles = roles_query(query_func=query_func).roles
        return expiration.filter(roles)

    @staticmethod
    def compile_users_from_schedule(
        schedule: ScheduleV1 | None,
    ) -> list[str]:
        """Return list of usernames from active schedule entries.

        Only includes users from schedule entries that are currently active
        (now is between start and end time).

        Args:
            schedule: List of schedule entries with start/end times and users

        Returns:
            List of usernames from active schedules
        """
        if not schedule:
            return []
        now = utc_now()
        all_usernames: list[str] = []
        for entry in schedule.schedule:
            start = ensure_utc(datetime.strptime(entry.start, DATE_FORMAT))  # noqa: DTZ007
            end = ensure_utc(datetime.strptime(entry.end, DATE_FORMAT))  # noqa: DTZ007
            if start <= now <= end:
                all_usernames.extend(u.org_username for u in entry.users)
        return all_usernames

    @staticmethod
    def compile_users_from_roles(roles: list[RoleV1] | None) -> list[str]:
        """Extract usernames from roles.

        Args:
            roles: List of role objects with users

        Returns:
            List of usernames from roles
        """

        return [user.org_username for role in roles or [] for user in role.users or []]

    async def fetch_owners(
        self,
        url: str,
        gh_to_org_username: Mapping[str, str],
        users_map: Mapping[str, UserV1],
    ) -> list[str]:
        """Fetch and process OWNERS from a single repository URL."""
        logging.debug(f"Fetching OWNERS from {url}")
        ref = "master"
        # allow passing repo_url:ref to select different branch
        if url.count(":") == 2:
            url, ref = url.rsplit(":", 1)

        response = await get_repo_owners(
            client=self.qontract_api_client, url_query=url, path="/", ref=ref
        )
        assert isinstance(response, RepoOwnersResponse)

        # Process owners inline
        result = []
        owners = (response.approvers or []) + (response.reviewers or [])
        for owner in owners:
            org_username = (
                gh_to_org_username.get(owner.lower())
                if response.provider == VCSProvider.GITHUB
                else owner
            )
            if org_username and org_username in users_map:
                user = users_map[org_username]
                if user.tag_on_merge_requests is not False:
                    result.append(user.org_username)
        return result

    async def compile_users_from_git_owners(
        self,
        urls: Iterable[str] | None,
        app_interface_users: list[UserV1],
    ) -> list[str]:
        """Extract usernames from git OWNERS files.

        Args:
            urls: List of git repo URLs to fetch OWNERS from
            app_interface_users: List of all App-Interface users

        Returns:
            List of usernames from git OWNERS files
        """
        if not urls:
            return []

        # map GitHub usernames to org_usernames
        gh_to_org_username = {
            user.github_username.lower(): user.org_username
            for user in app_interface_users
        }
        users_map = {user.org_username: user for user in app_interface_users}

        tasks = [self.fetch_owners(url, gh_to_org_username, users_map) for url in urls]
        results = await asyncio.gather(*tasks)

        # Extract usernames
        return list({username for usernames in results for username in usernames})

    async def compile_users_from_pagerduty_schedules(
        self,
        pagerduties: Iterable[PagerDutyTargetV1] | None,
    ) -> list[str]:
        """Extract usernames from PagerDuty schedules and escalation policies.

        Args:
            pagerduties: List of PagerDuty targets (schedules/escalation policies)

        Returns:
            List of usernames from PagerDuty
        """
        if not pagerduties:
            return []

        tasks: list[
            Coroutine[Any, Any, EscalationPolicyUsersResponse | ScheduleUsersResponse]
        ] = []
        for pagerduty in pagerduties:
            if pagerduty.schedule_id:
                tasks.append(
                    get_pagerduty_schedule_users(
                        client=self.qontract_api_client,
                        schedule_id=pagerduty.schedule_id,
                        instance=pagerduty.instance.name,
                    )
                )
            if pagerduty.escalation_policy_id:
                tasks.append(
                    get_pagerduty_escalation_policy_users(
                        client=self.qontract_api_client,
                        policy_id=pagerduty.escalation_policy_id,
                        instance=pagerduty.instance.name,
                    )
                )

        responses = await asyncio.gather(*tasks)

        # Extract usernames
        return [user.username for resp in responses for user in resp.users or []]

    async def _process_permission(
        self,
        permission: PermissionSlackUsergroupV1,
        app_interface_users: list[UserV1],
        desired_workspace_name: str | None,
        desired_usergroup_name: str | None,
    ) -> tuple[str, SlackUsergroup] | None:
        """Process a single permission and return (workspace_name, usergroup)."""
        if permission.skip or not permission.workspace.managed_usergroups:
            return None

        workspace_name = permission.workspace.name

        # Filter by workspace if specified
        if desired_workspace_name and workspace_name != desired_workspace_name:
            return None

        # Get usergroup handle
        usergroup_handle = permission.handle

        # Filter by usergroup if specified
        if desired_usergroup_name and usergroup_handle != desired_usergroup_name:
            return None

        # Validate usergroup is in managed_usergroups (SECURITY)
        if usergroup_handle not in permission.workspace.managed_usergroups:
            raise KeyError(
                f"[{permission.workspace.name}] usergroup {usergroup_handle} \
                    not in managed usergroups {permission.workspace.managed_usergroups}"
            )

        # Add users from the permission roles
        users = set(self.compile_users_from_roles(permission.roles))
        # Add users from the permission schedule (time-based on-call rotations)
        users.update(self.compile_users_from_schedule(permission.schedule))
        # Add users from git repo owners file
        users.update(
            await self.compile_users_from_git_owners(
                urls=permission.owners_from_repos,
                app_interface_users=app_interface_users,
            )
        )
        # Add users from PagerDuty schedules
        users.update(
            await self.compile_users_from_pagerduty_schedules(
                pagerduties=permission.pagerduty
            )
        )

        # Create config and usergroup
        config = SlackUsergroupConfig(
            description=permission.description or "",
            users=sorted(users),
            channels=sorted(set(permission.channels or [])),
        )
        usergroup = SlackUsergroup(handle=usergroup_handle, config=config)

        return (workspace_name, usergroup)

    async def compile_desired_state_from_permissions(
        self,
        permissions: list[PermissionSlackUsergroupV1],
        app_interface_users: list[UserV1],
        desired_workspace_name: str | None = None,
        desired_usergroup_name: str | None = None,
    ) -> list[SlackWorkspace]:
        """Compile the desired slack-usergroups from permissions."""
        # Process all permissions in parallel
        results = await asyncio.gather(*[
            self._process_permission(
                permission,
                app_interface_users,
                desired_workspace_name,
                desired_usergroup_name,
            )
            for permission in permissions
        ])

        # Build workspace -> usergroups mapping
        workspaces_map: dict[str, list[SlackUsergroup]] = defaultdict(list)
        for result in results:
            if result is not None:
                workspace_name, usergroup = result
                workspaces_map[workspace_name].append(usergroup)

        # Build workspace -> permission mapping for efficient lookup
        permissions_by_workspace = {p.workspace.name: p for p in permissions}

        # Build workspaces
        workspaces = []
        for workspace_name, usergroups in workspaces_map.items():
            permission = permissions_by_workspace[workspace_name]

            # Extract channel from workspace integrations
            default_channel = None
            if permission.workspace.integrations:
                for integration in permission.workspace.integrations:
                    if integration.name in {"slack-usergroups", QONTRACT_INTEGRATION}:
                        default_channel = integration.channel
                        break

            if not default_channel:
                logging.warning(
                    f"Workspace {workspace_name} has no slack-usergroups integration channel, skipping"
                )
                continue

            workspaces.append(
                SlackWorkspace(
                    name=workspace_name,
                    usergroups=usergroups,
                    managed_usergroups=permission.workspace.managed_usergroups
                    if not desired_usergroup_name
                    else [desired_usergroup_name],
                    default_channel=default_channel,
                )
            )

        return workspaces

    @staticmethod
    def compute_cluster_user_group(name: str) -> str:
        """Compute the cluster usergroup name."""
        return f"{name}-cluster"

    @staticmethod
    def include_user_to_cluster_usergroup(
        user: ClusterAccessUser, role: ClusterAccessRole
    ) -> bool:
        """Check the user should be notified (tag_on_cluster_updates)."""
        if user.tag_on_cluster_updates is not None:
            # if tag_on_cluster_updates is defined
            return user.tag_on_cluster_updates

        return role.tag_on_cluster_updates is not False

    def compile_desired_state_cluster_usergroups(
        self,
        workspaces: list[SlackWorkspace],
        clusters: Iterable[ClusterV1],
        roles: Iterable[ClusterAccessRole],
        desired_workspace_name: str | None = None,
        desired_usergroup_name: str | None = None,
    ) -> list[SlackWorkspace]:
        """Compile the desired slack-usergroups for all clusters."""
        cluster_users: dict[str, set[str]] = {}

        # Collect users per cluster from cluster access
        for role in roles:
            for access in role.access or []:
                if (
                    access.namespace
                    and bool(access.namespace.managed_roles)
                    and not bool(access.namespace.delete)
                ):
                    # namespace reference
                    cluster_name = access.namespace.cluster.name

                elif access.cluster and access.group:
                    # cluster access either via group or cluster role
                    cluster_name = access.cluster.name

                else:
                    # not a cluster/namespace access
                    continue

                if (
                    desired_usergroup_name
                    and self.compute_cluster_user_group(cluster_name)
                    != desired_usergroup_name
                ):
                    continue

                cluster_users.setdefault(cluster_name, set()).update([
                    user.org_username
                    for user in role.users
                    if self.include_user_to_cluster_usergroup(user, role)
                ])

        # Create usergroups for each cluster based on collected users
        for cluster in clusters:
            usergroup_handle = self.compute_cluster_user_group(cluster.name)
            # Filter by usergroup if specified
            if desired_usergroup_name and usergroup_handle != desired_usergroup_name:
                continue

            if not (users := set(cluster_users.get(cluster.name, []))):
                # no users for this cluster usergroup
                continue

            # Create config and usergroup
            config = SlackUsergroupConfig(
                description=f"Users with access to the {cluster.name} cluster",
                users=sorted(users),
                channels=[],
            )
            slack_usergroup = SlackUsergroup(handle=usergroup_handle, config=config)

            for workspace in workspaces:
                # Filter by workspace if specified
                if desired_workspace_name and workspace.name != desired_workspace_name:
                    continue
                assert isinstance(slack_usergroup.config.channels, list)  # for mypy
                slack_usergroup.config.channels.append(workspace.default_channel)
                workspace.usergroups.append(slack_usergroup)
                workspace.managed_usergroups = sorted(
                    set(workspace.managed_usergroups + [slack_usergroup.handle])
                )

        return workspaces

    async def reconcile(
        self,
        workspaces: list[SlackWorkspace],
        dry_run: bool = True,
    ) -> SlackUsergroupsTaskResponse:
        """Call qontract-api to reconcile Slack usergroups.

        Args:
            workspaces: List of Slack workspaces with usergroups
            dry_run: If True, only calculate actions without executing

        Returns:
            Response from qontract-api
        """
        request_data = SlackUsergroupsReconcileRequest(
            workspaces=[
                SlackWorkspaceRequest(
                    name=workspace.name,
                    usergroups=workspace.usergroups,
                    managed_usergroups=workspace.managed_usergroups,
                )
                for workspace in workspaces
            ],
            dry_run=dry_run,
        )
        response = await reconcile_slack_usergroups(
            client=self.qontract_api_client, body=request_data
        )
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration"""
        # TODO async gql client?
        gqlapi = gql.get_api()
        permissions = self.get_permissions(query_func=gqlapi.query)
        users = self.get_users(query_func=gqlapi.query)
        clusters = self.get_clusters(query_func=gqlapi.query)
        roles = self.get_roles(query_func=gqlapi.query)

        workspaces = await self.compile_desired_state_from_permissions(
            permissions=permissions,
            app_interface_users=users,
            desired_workspace_name=self.params.workspace_name,
            desired_usergroup_name=self.params.usergroup_name,
        )
        workspaces = self.compile_desired_state_cluster_usergroups(
            workspaces=workspaces,
            clusters=clusters,
            roles=roles,
            desired_workspace_name=self.params.workspace_name,
            desired_usergroup_name=self.params.usergroup_name,
        )

        if not workspaces:
            logging.warning("No desired state found, nothing to reconcile")
            return

        task = await self.reconcile(workspaces=workspaces, dry_run=dry_run)
        if dry_run:
            # wait for task completion and get the action list
            task_result = await slack_usergroups_task_status(
                client=self.qontract_api_client, task_id=task.id, timeout=300
            )
            if task_result.status == TaskStatus.PENDING:
                logging.error("Task did not complete within the timeout period")
                sys.exit(1)

            if task_result.actions:
                logging.info("Proposed actions:")
                for action in task_result.actions or []:
                    if isinstance(action, SlackUsergroupActionUpdateUsers):
                        logging.info(
                            f"{action.usergroup=} {action.users_to_add=} {action.users_to_remove=}"
                        )
                    else:
                        logging.info(action)

            if task_result.errors:
                logging.error(f"Errors encountered: {len(task_result.errors)}")
                for error in task_result.errors:
                    logging.error(f"  - {error}")
                sys.exit(1)
