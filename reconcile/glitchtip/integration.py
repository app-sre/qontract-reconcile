from collections.abc import (
    Callable,
    Iterable,
    Sequence,
)
from typing import (
    Any,
    Optional,
)

from reconcile.glitchtip.reconciler import GlitchtipReconciler
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    DEFINITION as GLITCHTIP_INSTANCE_DEFINITION,
)
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    DEFINITION as GLITCHTIP_PROJECT_DEFINITION,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    GlitchtipProjectsV1,
    RoleV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.ldap_groups.integration import LdapGroupsIntegration
from reconcile.typed_queries.app_interface_vault_settings import (
    get_app_interface_vault_settings,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Organization,
    Project,
    Team,
    User,
)
from reconcile.utils.internal_groups.client import InternalGroupsClient
from reconcile.utils.secret_reader import (
    SecretReaderBase,
    create_secret_reader,
)

QONTRACT_INTEGRATION = "glitchtip"
DEFAULT_MEMBER_ROLE = "member"


def filter_users(users: Iterable[User], ignore_users: Iterable[str]) -> list[User]:
    return [user for user in users if user.email not in ignore_users]


def get_user_role(organization: Organization, roles: RoleV1) -> str:
    for role in roles.glitchtip_roles or []:
        if role.organization.name == organization.name:
            return role.role
    # this can not be reached due to GQL but makes mypy happy
    return DEFAULT_MEMBER_ROLE


class GlitchtipException(Exception):
    pass


def fetch_current_state(
    glitchtip_client: GlitchtipClient, ignore_users: Iterable[str]
) -> list[Organization]:
    organizations = glitchtip_client.organizations()
    for organization in organizations:
        organization.teams = glitchtip_client.teams(organization_slug=organization.slug)
        organization.projects = glitchtip_client.projects(
            organization_slug=organization.slug
        )
        organization.users = filter_users(
            glitchtip_client.organization_users(organization_slug=organization.slug),
            ignore_users,
        )
        for team in organization.teams:
            team.users = glitchtip_client.team_users(
                organization_slug=organization.slug, team_slug=team.slug
            )

    return organizations


def fetch_desired_state(
    glitchtip_projects: Sequence[GlitchtipProjectsV1],
    mail_domain: str,
    internal_groups_client: InternalGroupsClient,
) -> list[Organization]:
    organizations: dict[str, Organization] = {}
    for glitchtip_project in glitchtip_projects:
        organization = organizations.setdefault(
            glitchtip_project.organization.name,
            Organization(name=glitchtip_project.organization.name),
        )
        project = Project(
            name=glitchtip_project.name,
            platform=glitchtip_project.platform,
            slug=glitchtip_project.project_id if glitchtip_project.project_id else "",
            event_throttle_rate=glitchtip_project.event_throttle_rate or 0,
        )
        # Check project is unique within an organization
        if project.name in [p.name for p in organization.projects]:
            raise GlitchtipException(f'project name "{project.name}" already in use!')
        for glitchtip_team in glitchtip_project.teams:
            users: list[User] = []

            # Get users via roles
            for role in glitchtip_team.roles:
                for role_user in role.users:
                    users.append(
                        User(
                            email=f"{role_user.org_username}@{mail_domain}",
                            role=get_user_role(organization, role),
                        )
                    )

            # Get users via ldap
            for ldap_group in glitchtip_team.ldap_groups or []:
                for member in internal_groups_client.group(ldap_group).members:
                    users.append(
                        User(
                            email=f"{member.id}@{mail_domain}",
                            role=glitchtip_team.members_organization_role
                            or DEFAULT_MEMBER_ROLE,
                        )
                    )

            # set(users) will take the first occurrence of a user, so the users from roles will be preferred
            team = Team(name=glitchtip_team.name, users=set(users))
            project.teams.append(team)
            if team not in organization.teams:
                organization.teams.append(team)

            for user in team.users:
                if user not in organization.users:
                    organization.users.append(user)
        organization.projects.append(project)
    return list(organizations.values())


def get_glitchtip_projects(query_func: Callable) -> list[GlitchtipProjectsV1]:
    glitchtip_projects = (
        glitchtip_project_query(query_func=query_func).glitchtip_projects or []
    )
    for project in glitchtip_projects:
        # either org.owners or project.app must be set
        if not project.organization.owners and not project.app:
            raise ValueError(
                f"Either owners in organization {project.organization.name} or app must be set for project {project.name}"
            )

    return glitchtip_projects


def get_internal_groups_client(
    query_func: Callable, secret_reader: SecretReaderBase
) -> InternalGroupsClient:
    ldap_groups_settings = LdapGroupsIntegration.get_integration_settings(query_func)
    secret = secret_reader.read_all_secret(ldap_groups_settings.credentials)
    return InternalGroupsClient(
        secret["api_url"],
        secret["issuer_url"],
        secret["client_id"],
        secret["client_secret"],
    )


@defer
def run(
    dry_run: bool, instance: Optional[str] = None, defer: Optional[Callable] = None
) -> None:
    gqlapi = gql.get_api()
    vault_settings = get_app_interface_vault_settings()
    secret_reader = create_secret_reader(use_vault=vault_settings.vault)
    internal_groups_client = get_internal_groups_client(gqlapi.query, secret_reader)
    if defer:
        defer(internal_groups_client.close)

    glitchtip_instances = glitchtip_instance_query(query_func=gqlapi.query).instances
    glitchtip_projects = get_glitchtip_projects(query_func=gqlapi.query)

    for glitchtip_instance in glitchtip_instances:
        if instance and glitchtip_instance.name != instance:
            continue

        glitchtip_client = GlitchtipClient(
            host=glitchtip_instance.console_url,
            token=secret_reader.read_secret(glitchtip_instance.automation_token),
            read_timeout=glitchtip_instance.read_timeout,
            max_retries=glitchtip_instance.max_retries,
        )
        current_state = fetch_current_state(
            glitchtip_client=glitchtip_client,
            # the automation user isn't managed by app-interface (chicken - egg problem), so just ignore it
            ignore_users=[
                secret_reader.read_secret(glitchtip_instance.automation_user_email)
            ],
        )
        desired_state = fetch_desired_state(
            glitchtip_projects=[
                p
                for p in glitchtip_projects
                if p.organization.instance.name == glitchtip_instance.name
            ],
            mail_domain=glitchtip_instance.mail_domain or "redhat.com",
            internal_groups_client=internal_groups_client,
        )

        reconciler = GlitchtipReconciler(glitchtip_client, dry_run)
        reconciler.reconcile(current_state, desired_state)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {
        "projects": gqlapi.query(GLITCHTIP_PROJECT_DEFINITION)["glitchtip_projects"],
        "instances": gqlapi.query(GLITCHTIP_INSTANCE_DEFINITION)["instances"],
    }
