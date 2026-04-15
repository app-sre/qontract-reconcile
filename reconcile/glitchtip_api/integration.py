"""Glitchtip API integration: manages Glitchtip organizations, teams, projects, and users."""

import asyncio
import logging
import sys
from collections import defaultdict
from collections.abc import Callable

from qontract_api_client.api.external.ldap_group_members import (
    asyncio as get_ldap_group_members,
)
from qontract_api_client.api.integrations.glitchtip import (
    asyncio as reconcile_glitchtip,
)
from qontract_api_client.api.integrations.glitchtip_task_status import (
    asyncio as glitchtip_task_status,
)
from qontract_api_client.models.gi_instance import GIInstance
from qontract_api_client.models.gi_organization import GIOrganization
from qontract_api_client.models.gi_project import GIProject
from qontract_api_client.models.glitchtip_reconcile_request import (
    GlitchtipReconcileRequest,
)
from qontract_api_client.models.glitchtip_team import GlitchtipTeam
from qontract_api_client.models.glitchtip_user import GlitchtipUser
from qontract_api_client.models.secret import Secret
from qontract_api_client.models.task_status import TaskStatus
from qontract_utils.glitchtip_api import slugify

from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    GlitchtipProjectV1,
    GlitchtipProjectV1_GlitchtipOrganizationV1,
    GlitchtipTeamV1,
    RoleV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.gql_definitions.ldap_groups.settings import (
    query as ldap_groups_settings_query,
)
from reconcile.utils import gql
from reconcile.utils.exceptions import (
    AppInterfaceLdapGroupsSettingsError,
    AppInterfaceSettingsError,
)
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "glitchtip-api"
DEFAULT_MEMBER_ROLE = "member"
_LDAP_CLIENT_SECRET_FIELD = "client_secret"

# GlitchTip org roles ordered from lowest to highest privilege.
# Used to deterministically resolve a user's org role when they appear in
# multiple teams with different role assignments.
_ROLE_PRECEDENCE: list[str] = ["member", "contributor", "manager", "admin", "owner"]


def _highest_role(role_a: str, role_b: str) -> str:
    """Return the higher-privilege of two GlitchTip org roles.

    Unknown roles are treated as lowest privilege so they never silently
    override a known role.
    """
    idx_a = _ROLE_PRECEDENCE.index(role_a) if role_a in _ROLE_PRECEDENCE else -1
    idx_b = _ROLE_PRECEDENCE.index(role_b) if role_b in _ROLE_PRECEDENCE else -1
    return role_a if idx_a >= idx_b else role_b


def _get_user_role(
    organization: GlitchtipProjectV1_GlitchtipOrganizationV1, role: RoleV1
) -> str:
    for glitchtip_role in role.glitchtip_roles or []:
        if glitchtip_role.organization.name == organization.name:
            return glitchtip_role.role
    return DEFAULT_MEMBER_ROLE


class GlitchtipApiIntegrationParams(PydanticRunParams):
    instance: str | None = None


class GlitchtipApiIntegration(
    QontractReconcileApiIntegration[GlitchtipApiIntegrationParams]
):
    """Manage Glitchtip organizations, teams, projects, and users."""

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_glitchtip_projects(self, query_func: Callable) -> list[GlitchtipProjectV1]:
        return glitchtip_project_query(query_func=query_func).glitchtip_projects or []

    async def _get_ldap_member_ids(
        self,
        group_name: str,
        ldap_cred_path: str,
        ldap_cred_version: int | None,
        ldap_api_url: str,
        ldap_token_url: str,
        ldap_client_id: str,
    ) -> list[str]:
        """Fetch LDAP group member IDs via qontract-api external endpoint."""
        response = await get_ldap_group_members(
            client=self.qontract_api_client,
            group_name=group_name,
            secret_manager_url=self.secret_manager_url,
            path=ldap_cred_path,
            field=_LDAP_CLIENT_SECRET_FIELD,
            version=ldap_cred_version,
            base_url=ldap_api_url,
            token_url=ldap_token_url,
            client_id=ldap_client_id,
        )
        return [m.id for m in (response.members or [])]

    @staticmethod
    def _build_team_users(
        glitchtip_team: GlitchtipTeamV1,
        organization: GlitchtipProjectV1_GlitchtipOrganizationV1,
        mail_domain: str,
        ldap_members: dict[str, list[str]],
    ) -> dict[str, GlitchtipUser]:
        """Build email→GlitchtipUser map for a team (roles take precedence over LDAP).

        Args:
            glitchtip_team: Team definition from GQL
            organization: Parent organization (for role lookup)
            mail_domain: Domain appended to usernames to form email addresses
            ldap_members: Pre-fetched cache of group name → member ID list
        """
        users_by_email: dict[str, GlitchtipUser] = {}

        for role in glitchtip_team.roles:
            role_str = _get_user_role(organization, role)
            for user in role.users:
                email = f"{user.org_username}@{mail_domain}"
                users_by_email[email] = GlitchtipUser(email=email, role=role_str)

        if glitchtip_team.ldap_groups:
            member_role = (
                glitchtip_team.members_organization_role or DEFAULT_MEMBER_ROLE
            )
            for group in glitchtip_team.ldap_groups:
                for member_id in ldap_members.get(group, []):
                    email = f"{member_id}@{mail_domain}"
                    if email not in users_by_email:
                        users_by_email[email] = GlitchtipUser(
                            email=email, role=member_role
                        )

        return users_by_email

    async def _build_desired_state(
        self,
        glitchtip_projects: list[GlitchtipProjectV1],
        mail_domain: str,
        ldap_api_url: str,
        ldap_token_url: str,
        ldap_client_id: str,
        ldap_cred_path: str,
        ldap_cred_version: int | None,
    ) -> list[GIOrganization]:
        org_teams: dict[str, dict[str, GlitchtipTeam]] = defaultdict(dict)
        org_projects: dict[str, list[GIProject]] = defaultdict(list)
        org_users: dict[str, dict[str, GlitchtipUser]] = defaultdict(dict)

        # Pre-fetch all unique LDAP groups concurrently to avoid redundant API calls
        # when the same group appears across multiple teams.
        all_ldap_groups = {
            group
            for proj in glitchtip_projects
            for team in proj.teams
            for group in (team.ldap_groups or [])
        }
        if all_ldap_groups:
            ordered_groups = sorted(all_ldap_groups)
            member_lists = await asyncio.gather(*[
                self._get_ldap_member_ids(
                    group_name=group,
                    ldap_cred_path=ldap_cred_path,
                    ldap_cred_version=ldap_cred_version,
                    ldap_api_url=ldap_api_url,
                    ldap_token_url=ldap_token_url,
                    ldap_client_id=ldap_client_id,
                )
                for group in ordered_groups
            ])
            ldap_members: dict[str, list[str]] = dict(
                zip(ordered_groups, member_lists, strict=True)
            )
        else:
            ldap_members = {}

        for proj in glitchtip_projects:
            org_name = proj.organization.name
            project_team_slugs: list[str] = []

            for glitchtip_team in proj.teams:
                team_slug = slugify(glitchtip_team.name)
                project_team_slugs.append(team_slug)

                if team_slug not in org_teams[org_name]:
                    users_by_email = self._build_team_users(
                        glitchtip_team=glitchtip_team,
                        organization=proj.organization,
                        mail_domain=mail_domain,
                        ldap_members=ldap_members,
                    )
                    org_teams[org_name][team_slug] = GlitchtipTeam(
                        name=glitchtip_team.name,
                        users=list(users_by_email.values()),
                    )
                    for email, user in users_by_email.items():
                        if email not in org_users[org_name]:
                            org_users[org_name][email] = user
                        else:
                            # User in multiple teams — keep the highest-privilege role
                            # to avoid non-deterministic first-team-wins assignment.
                            # Treat Unset (missing) role as DEFAULT_MEMBER_ROLE.
                            existing = org_users[org_name][email]
                            new_role = (
                                user.role
                                if isinstance(user.role, str)
                                else DEFAULT_MEMBER_ROLE
                            )
                            cur_role = (
                                existing.role
                                if isinstance(existing.role, str)
                                else DEFAULT_MEMBER_ROLE
                            )
                            best_role = _highest_role(new_role, cur_role)
                            if best_role != cur_role:
                                org_users[org_name][email] = GlitchtipUser(
                                    email=email, role=best_role
                                )

            if not project_team_slugs:
                raise ValueError(
                    f"Project '{proj.name}' in org '{proj.organization.name}' "
                    f"has no teams assigned — cannot reconcile"
                )

            project_slug = proj.project_id or slugify(proj.name)
            org_projects[org_name].append(
                GIProject(
                    name=proj.name,
                    slug=project_slug,
                    platform=proj.platform,
                    event_throttle_rate=proj.event_throttle_rate or 0,
                    teams=project_team_slugs,
                )
            )

        all_org_names = set(org_teams) | set(org_projects)
        return [
            GIOrganization(
                name=org_name,
                teams=list(org_teams[org_name].values()),
                projects=org_projects[org_name],
                users=list(org_users[org_name].values()),
            )
            for org_name in all_org_names
        ]

    async def async_run(self, dry_run: bool) -> None:
        gqlapi = gql.get_api()

        glitchtip_instances = glitchtip_instance_query(
            query_func=gqlapi.query
        ).instances
        glitchtip_projects = self.get_glitchtip_projects(query_func=gqlapi.query)

        ldap_settings_data = ldap_groups_settings_query(gqlapi.query)
        if not ldap_settings_data.settings:
            raise AppInterfaceSettingsError("No app-interface settings found.")
        if not ldap_settings_data.settings[0].ldap_groups:
            raise AppInterfaceLdapGroupsSettingsError(
                "No app-interface ldap-groups settings found."
            )
        ldap_settings = ldap_settings_data.settings[0].ldap_groups
        ldap_credentials = self.secret_reader.read_all_secret(ldap_settings.credentials)
        missing = [
            k
            for k in ("api_url", "issuer_url", "client_id")
            if not ldap_credentials.get(k)
        ]
        if missing:
            raise ValueError(
                f"Missing required LDAP credential fields in secret "
                f"'{ldap_settings.credentials.path}': {missing}"
            )
        ldap_api_url: str = ldap_credentials["api_url"]
        ldap_token_url: str = ldap_credentials["issuer_url"]
        ldap_client_id: str = ldap_credentials["client_id"]
        ldap_cred_path: str = ldap_settings.credentials.path
        ldap_cred_version: int | None = ldap_settings.credentials.version

        projects_by_instance: dict[str, list[GlitchtipProjectV1]] = defaultdict(list)
        for proj in glitchtip_projects:
            projects_by_instance[proj.organization.instance.name].append(proj)

        filtered_instances = [
            inst
            for inst in glitchtip_instances
            if not self.params.instance or inst.name == self.params.instance
        ]

        all_organizations = await asyncio.gather(*[
            self._build_desired_state(
                glitchtip_projects=projects_by_instance[inst.name],
                mail_domain=inst.mail_domain or "redhat.com",
                ldap_api_url=ldap_api_url,
                ldap_token_url=ldap_token_url,
                ldap_client_id=ldap_client_id,
                ldap_cred_path=ldap_cred_path,
                ldap_cred_version=ldap_cred_version,
            )
            for inst in filtered_instances
        ])

        instances: list[GIInstance] = [
            GIInstance(
                name=inst.name,
                console_url=inst.console_url,
                token=Secret(
                    secret_manager_url=self.secret_manager_url,
                    path=inst.automation_token.path,
                    field=inst.automation_token.field,
                    version=inst.automation_token.version,
                ),
                automation_user_email=Secret(
                    secret_manager_url=self.secret_manager_url,
                    path=inst.automation_user_email.path,
                    field=inst.automation_user_email.field,
                    version=inst.automation_user_email.version,
                ),
                read_timeout=inst.read_timeout or 30,
                max_retries=inst.max_retries or 3,
                organizations=organizations,
            )
            for inst, organizations in zip(
                filtered_instances, all_organizations, strict=True
            )
        ]

        if not instances:
            logging.warning("No Glitchtip instances to reconcile")
            return

        task = await reconcile_glitchtip(
            client=self.qontract_api_client,
            body=GlitchtipReconcileRequest(instances=instances, dry_run=dry_run),
        )
        logging.info(f"request_id: {task.id}")

        if not dry_run:
            # In non-dry-run, we expect the task to complete asynchronously in the background
            # and change events will be automatically published via the events framework.
            return

        task_result = await glitchtip_task_status(
            client=self.qontract_api_client, task_id=task.id, timeout=300
        )

        if task_result.status == TaskStatus.PENDING:
            logging.error("Glitchtip task did not complete within the timeout period")
            sys.exit(1)

        for action in task_result.actions or []:
            logging.info(action.to_dict())

        if task_result.errors:
            logging.error(f"Errors encountered: {len(task_result.errors)}")
            for error in task_result.errors:
                logging.error(f"  - {error}")
            sys.exit(1)
