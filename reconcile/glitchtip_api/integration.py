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
from reconcile.ldap_groups.integration import LdapGroupsIntegration
from reconcile.utils import gql
from reconcile.utils.runtime.integration import (
    PydanticRunParams,
    QontractReconcileApiIntegration,
)

QONTRACT_INTEGRATION = "glitchtip-api"
DEFAULT_MEMBER_ROLE = "member"
_LDAP_CLIENT_SECRET_FIELD = "client_secret"



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

    async def _build_team_users(
        self,
        glitchtip_team: GlitchtipTeamV1,
        organization: GlitchtipProjectV1_GlitchtipOrganizationV1,
        mail_domain: str,
        ldap_api_url: str,
        ldap_token_url: str,
        ldap_client_id: str,
        ldap_cred_path: str,
        ldap_cred_version: int | None,
    ) -> dict[str, GlitchtipUser]:
        """Build email→GlitchtipUser map for a team (roles take precedence over LDAP)."""
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
            tasks = [
                self._get_ldap_member_ids(
                    group_name=group,
                    ldap_cred_path=ldap_cred_path,
                    ldap_cred_version=ldap_cred_version,
                    ldap_api_url=ldap_api_url,
                    ldap_token_url=ldap_token_url,
                    ldap_client_id=ldap_client_id,
                )
                for group in glitchtip_team.ldap_groups
            ]
            all_member_lists = await asyncio.gather(*tasks)
            for member_ids in all_member_lists:
                for member_id in member_ids:
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

        for proj in glitchtip_projects:
            org_name = proj.organization.name
            project_team_slugs: list[str] = []

            for glitchtip_team in proj.teams:
                team_slug = slugify(glitchtip_team.name)
                project_team_slugs.append(team_slug)

                if team_slug not in org_teams[org_name]:
                    users_by_email = await self._build_team_users(
                        glitchtip_team=glitchtip_team,
                        organization=proj.organization,
                        mail_domain=mail_domain,
                        ldap_api_url=ldap_api_url,
                        ldap_token_url=ldap_token_url,
                        ldap_client_id=ldap_client_id,
                        ldap_cred_path=ldap_cred_path,
                        ldap_cred_version=ldap_cred_version,
                    )
                    org_teams[org_name][team_slug] = GlitchtipTeam(
                        name=glitchtip_team.name,
                        users=list(users_by_email.values()),
                    )
                    for email, user in users_by_email.items():
                        if email not in org_users[org_name]:
                            org_users[org_name][email] = user

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

        ldap_settings = LdapGroupsIntegration.get_integration_settings(gqlapi.query)
        ldap_credentials = self.secret_reader.read_all_secret(ldap_settings.credentials)
        ldap_api_url: str = ldap_credentials.get("api_url", "")
        ldap_token_url: str = ldap_credentials.get("issuer_url", "")
        ldap_client_id: str = ldap_credentials.get("client_id", "")
        ldap_cred_path: str = ldap_settings.credentials.path
        ldap_cred_version: int | None = ldap_settings.credentials.version

        projects_by_instance: dict[str, list[GlitchtipProjectV1]] = defaultdict(list)
        for proj in glitchtip_projects:
            projects_by_instance[proj.organization.instance.name].append(proj)

        instances: list[GIInstance] = []
        for glitchtip_instance in glitchtip_instances:
            if self.params.instance and glitchtip_instance.name != self.params.instance:
                continue

            organizations = await self._build_desired_state(
                glitchtip_projects=projects_by_instance[glitchtip_instance.name],
                mail_domain=glitchtip_instance.mail_domain or "redhat.com",
                ldap_api_url=ldap_api_url,
                ldap_token_url=ldap_token_url,
                ldap_client_id=ldap_client_id,
                ldap_cred_path=ldap_cred_path,
                ldap_cred_version=ldap_cred_version,
            )

            instances.append(
                GIInstance(
                    name=glitchtip_instance.name,
                    console_url=glitchtip_instance.console_url,
                    token=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=glitchtip_instance.automation_token.path,
                        field=glitchtip_instance.automation_token.field,
                        version=glitchtip_instance.automation_token.version,
                    ),
                    automation_user_email=Secret(
                        secret_manager_url=self.secret_manager_url,
                        path=glitchtip_instance.automation_user_email.path,
                        field=glitchtip_instance.automation_user_email.field,
                        version=glitchtip_instance.automation_user_email.version,
                    ),
                    read_timeout=glitchtip_instance.read_timeout or 30,
                    max_retries=glitchtip_instance.max_retries or 3,
                    organizations=organizations,
                )
            )

        if not instances:
            logging.warning("No Glitchtip instances to reconcile")
            return

        task = await reconcile_glitchtip(
            client=self.qontract_api_client,
            body=GlitchtipReconcileRequest(instances=instances, dry_run=dry_run),
        )
        logging.info(f"request_id: {task.id}")

        if not dry_run:
            return

        task_result = await glitchtip_task_status(
            client=self.qontract_api_client, task_id=task.id, timeout=300
        )

        if task_result.status == TaskStatus.PENDING:
            logging.error("Glitchtip task did not complete within the timeout period")
            sys.exit(1)

        for action in task_result.actions or []:
            logging.info(f"action_type={action.action_type}")

        if task_result.errors:
            logging.error(f"Errors encountered: {len(task_result.errors)}")
            for error in task_result.errors:
                logging.error(f"  - {error}")
            sys.exit(1)
