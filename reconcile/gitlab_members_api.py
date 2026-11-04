"""GitLab group membership reconciliation via qontract-api.

This is the client-side integration that calls qontract-api instead of
directly managing GitLab group membership.

See ADR-002 (Client-Side GraphQL) and ADR-008 (Integration Naming).

Key differences from reconcile/gitlab_members.py:
- Suffix '_api' indicates API-based integration
- GraphQL queries for desired state happen client-side here
- Actual reconciliation (GitLab API calls) happens server-side (qontract-api)
- PagerDuty on-call lookups happen via qontract-api external endpoints
  instead of the pypd-based reconcile/utils/pagerduty_api.py
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from qontract_api_client.client import gitlab_members as reconcile_gitlab_members
from qontract_api_client.client import (
    pagerduty_escalation_policy_users,
    pagerduty_schedule_users,
)
from qontract_api_client.schemas import (
    EscalationPolicyUsersResponse,
    GitlabMemberConfig,
    GitlabMembersGroupConfig,
    GitlabMembersInstanceConfig,
    GitlabMembersReconcileRequest,
    GitlabMembersTaskResult,
    ScheduleUsersResponse,
    Secret,
    TaskStatus,
)
from qontract_utils.exceptions import IntegrationError
from qontract_utils.gitlab_api import GitlabAccessLevel

from reconcile.gql_definitions.gitlab_members_api.gitlab_instances import (
    GitlabInstanceV1,
)
from reconcile.gql_definitions.gitlab_members_api.gitlab_instances import (
    query as gitlab_instances_query,
)
from reconcile.gql_definitions.gitlab_members_api.permissions import (
    PermissionGitlabGroupMembershipV1,
    UserV1,
)
from reconcile.gql_definitions.gitlab_members_api.permissions import (
    query as permissions_query,
)
from reconcile.typed_queries.users import get_users
from reconcile.utils import gql
from reconcile.utils.exceptions import AppInterfaceSettingsError
from reconcile.utils.membershipsources.async_resolver import resolve_role_members
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Coroutine, Iterable

    from qontract_api_client.schemas import GitlabMembersTaskResponse

    from reconcile.gql_definitions.fragments.user import User
    from reconcile.gql_definitions.gitlab_members_api.permissions import (
        BotV1,
        PagerDutyTargetV1,
    )

QONTRACT_INTEGRATION = "gitlab-members-api"


class GitlabMembersIntegrationParams(PydanticRunParams):
    """Parameters for gitlab-members-api integration."""


def _query_permissions(query_func: Callable) -> list[PermissionGitlabGroupMembershipV1]:
    return [
        p
        for p in permissions_query(query_func=query_func).permissions
        if isinstance(p, PermissionGitlabGroupMembershipV1)
    ]


def _pagerduty_name(user: User) -> str:
    """The PagerDuty-equivalent name for an app-interface user: an explicit
    override, else the org_username itself."""
    return user.pagerduty_username or user.org_username


def _add_or_update_member(
    members: dict[str, GitlabMemberConfig],
    username: str,
    access_level: GitlabAccessLevel,
) -> None:
    existing = members.get(username)
    if (
        existing is None
        or access_level.to_access_level()
        > GitlabAccessLevel(existing.access_level.value).to_access_level()
    ):
        members[username] = GitlabMemberConfig(
            username=username, access_level=access_level
        )


class GitlabMembersIntegration(
    QontractReconcileApiIntegration[GitlabMembersIntegrationParams]
):
    """Manage GitLab group membership via qontract-api."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    @staticmethod
    def get_gitlab_instance(query_func: Callable) -> GitlabInstanceV1:
        """Return the single managed GitLab instance."""
        if instances := gitlab_instances_query(query_func=query_func).instances:
            if len(instances) != 1:
                raise AppInterfaceSettingsError("More than one gitlab instance found!")
            return instances[0]
        raise AppInterfaceSettingsError("No gitlab instance found!")

    @staticmethod
    async def get_permissions(
        query_func: Callable, *, managed_groups: Collection[str]
    ) -> list[PermissionGitlabGroupMembershipV1]:
        """Fetch GitLab group membership permissions with resolved role memberships."""
        permissions = [
            permission.model_copy() for permission in _query_permissions(query_func)
        ]
        resolved_roles = await resolve_role_members(
            [role for permission in permissions for role in permission.roles or []],
            user_cls=UserV1,
            query_func=query_func,
        )
        roles_by_name = {role.name: role for role in resolved_roles}
        for permission in permissions:
            if permission.roles is not None:
                permission.roles = [
                    roles_by_name[role.name] for role in permission.roles
                ]
        permissions = [p for p in permissions if p.group in managed_groups]
        return permissions

    async def compile_users_from_pagerduty(
        self,
        pagerduties: Iterable[PagerDutyTargetV1] | None,
        app_interface_users: list[User],
        group_name: str,
    ) -> list[str]:
        """Resolve on-call org_usernames from PagerDuty schedules/escalation policies.

        Args:
            pagerduties: List of PagerDuty targets (schedules/escalation policies)
            app_interface_users: All app-interface users, matched against
                PagerDuty usernames via `pagerduty_username` (falling back to
                `org_username`)
            group_name: GitLab group name, for warning log context

        Returns:
            List of org_usernames currently on-call

        Raises:
            IntegrationError: if a PagerDuty target has neither a schedule
                nor an escalation policy configured
        """
        if not pagerduties:
            return []

        tasks: list[
            Coroutine[Any, Any, EscalationPolicyUsersResponse | ScheduleUsersResponse]
        ] = []
        for pagerduty in pagerduties:
            if pagerduty.schedule_id is None and pagerduty.escalation_policy_id is None:
                raise IntegrationError(
                    f"pagerduty {pagerduty.name}: Either schedule_id or "
                    "escalation_policy_id must be set!"
                )
            if pagerduty.schedule_id:
                tasks.append(
                    pagerduty_schedule_users(
                        schedule_id=pagerduty.schedule_id,
                        secret_manager_url=self.secret_manager_url,
                        path=pagerduty.instance.token.path,
                        field=pagerduty.instance.token.field,
                        version=pagerduty.instance.token.version,
                    )
                )
            if pagerduty.escalation_policy_id:
                tasks.append(
                    pagerduty_escalation_policy_users(
                        policy_id=pagerduty.escalation_policy_id,
                        secret_manager_url=self.secret_manager_url,
                        path=pagerduty.instance.token.path,
                        field=pagerduty.instance.token.field,
                        version=pagerduty.instance.token.version,
                    )
                )

        responses = await asyncio.gather(*tasks)

        # qontract-api's PagerDuty client already drops the "nobody"
        # placeholder (no one on-call) and strips plus-addressing from
        # usernames, so these are ready to match as-is.
        pagerduty_names = [
            user.username for resp in responses for user in resp.users or []
        ]

        org_username_by_pagerduty_name = {
            _pagerduty_name(user): user.org_username for user in app_interface_users
        }

        if not_found := [
            name
            for name in pagerduty_names
            if name not in org_username_by_pagerduty_name
        ]:
            logging.warning(
                f"[{group_name}] PagerDuty username not found in app-interface: "
                f"{not_found} (hint: user files should contain pagerduty_username "
                "if it is different than org_username)"
            )

        return [
            org_username_by_pagerduty_name[name]
            for name in pagerduty_names
            if name in org_username_by_pagerduty_name
        ]

    async def compile_group_members(
        self,
        group_name: str,
        permissions: list[PermissionGitlabGroupMembershipV1],
        app_interface_users: list[User],
    ) -> list[GitlabMemberConfig]:
        """Compile the desired member list for a single managed group."""
        members: dict[str, GitlabMemberConfig] = {}
        for permission in permissions:
            if permission.group != group_name:
                continue
            access_level = GitlabAccessLevel(permission.access.lower())
            for role in permission.roles or []:
                role_members: list[UserV1 | BotV1] = [*role.users, *(role.bots or [])]
                for member in role_members:
                    if username := member.org_username:
                        _add_or_update_member(members, username, access_level)
            if permission.pagerduty:
                for username in await self.compile_users_from_pagerduty(
                    permission.pagerduty, app_interface_users, group_name
                ):
                    _add_or_update_member(members, username, access_level)
        return list(members.values())

    async def compile_desired_state(
        self,
        instance: GitlabInstanceV1,
        permissions: list[PermissionGitlabGroupMembershipV1],
        app_interface_users: list[User],
    ) -> GitlabMembersInstanceConfig:
        """Compile the full desired membership state for the GitLab instance."""
        groups = await asyncio.gather(*[
            self.compile_group_members(group_name, permissions, app_interface_users)
            for group_name in instance.managed_groups
        ])
        return GitlabMembersInstanceConfig(
            name=instance.name,
            url=instance.url,
            ssl_verify=(True if instance.ssl_verify is None else instance.ssl_verify),
            token=Secret(
                secret_manager_url=self.secret_manager_url,
                path=instance.token.path,
                field=instance.token.field,
                version=instance.token.version,
            ),
            groups=[
                GitlabMembersGroupConfig(group=group_name, members=members)
                for group_name, members in zip(
                    instance.managed_groups, groups, strict=True
                )
            ],
        )

    async def reconcile(
        self, instances: list[GitlabMembersInstanceConfig], dry_run: bool
    ) -> GitlabMembersTaskResponse:
        """Send desired state to qontract-api and return task response."""
        request = GitlabMembersReconcileRequest(instances=instances, dry_run=dry_run)
        with self.log_api_exceptions():
            response = await reconcile_gitlab_members(request)
        logging.info(f"request_id: {response.id}")
        return response

    async def async_run(self, dry_run: bool) -> None:
        """Run the integration."""
        gqlapi = gql.get_api()
        instance = self.get_gitlab_instance(gqlapi.query)
        permissions = await self.get_permissions(
            query_func=gqlapi.query, managed_groups=instance.managed_groups
        )
        app_interface_users = get_users(query_func=gqlapi.query)
        desired_instance = await self.compile_desired_state(
            instance, permissions, app_interface_users
        )

        task = await self.reconcile(instances=[desired_instance], dry_run=dry_run)

        if not dry_run:
            # In non-dry-run, the task completes asynchronously in the background
            # and change events will be published via the events framework.
            return

        task_result = await self.poll_task_status(
            status_url=task.status_url, result_type=GitlabMembersTaskResult
        )
        if task_result.status == TaskStatus.PENDING:
            raise IntegrationError(
                "gitlab-members-api: task did not complete within the timeout period"
            )

        for action in task_result.actions or []:
            logging.info(f"{action.action_type=} {action.group=} {action.username=}")

        if task_result.errors:
            errors_summary = "; ".join(task_result.errors)
            raise IntegrationError(
                f"gitlab-members-api: {len(task_result.errors)} error(s): {errors_summary}"
            )
