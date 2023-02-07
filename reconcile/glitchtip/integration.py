from collections.abc import (
    Iterable,
    Sequence,
)
from typing import (
    Any,
    Optional,
)

from reconcile import queries
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
from reconcile.gql_definitions.glitchtip.glitchtip_settings import (
    query as glitchtip_settings_query,
)
from reconcile.utils import gql
from reconcile.utils.glitchtip import (
    GlitchtipClient,
    Organization,
    Project,
    Team,
    User,
)
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "glitchtip"


def filter_users(users: Iterable[User], ignore_users: Iterable[str]) -> list[User]:
    return [user for user in users if user.email not in ignore_users]


def get_user_role(organization: Organization, roles: RoleV1) -> str:
    for role in roles.glitchtip_roles or []:
        if role.organization.name == organization.name:
            return role.role
    # this can not be reached due to GQL but makes mypy happy
    return "member"


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
    glitchtip_projects: Sequence[GlitchtipProjectsV1], mail_domain: str
) -> list[Organization]:
    organizations: dict[str, Organization] = {}
    for glitchtip_project in glitchtip_projects:
        organization = organizations.setdefault(
            glitchtip_project.organization.name,
            Organization(name=glitchtip_project.organization.name),
        )
        project = Project(
            name=glitchtip_project.name, platform=glitchtip_project.platform
        )
        # Check project is unique within an organization
        if project.name in [p.name for p in organization.projects]:
            raise GlitchtipException(f'project name "{project.name}" already in use!')
        for glitchtip_team in glitchtip_project.teams:
            users: list[User] = []
            for role in glitchtip_team.roles:
                for role_user in role.users:
                    users.append(
                        User(
                            email=f"{role_user.org_username}@{mail_domain}",
                            role=get_user_role(organization, role),
                        )
                    )

            team = Team(name=glitchtip_team.name, users=users)
            project.teams.append(team)
            if team not in organization.teams:
                organization.teams.append(team)

            for user in team.users:
                if user not in organization.users:
                    organization.users.append(user)
        organization.projects.append(project)
    return list(organizations.values())


def run(dry_run: bool, instance: Optional[str] = None) -> None:
    gqlapi = gql.get_api()
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    read_timeout = 30
    max_retries = 3
    mail_domain = "redhat.com"
    if _s := glitchtip_settings_query(query_func=gqlapi.query).settings:
        if _gs := _s[0].glitchtip:
            if _gs.read_timeout is not None:
                read_timeout = _gs.read_timeout
            if _gs.max_retries is not None:
                max_retries = _gs.max_retries
            if _gs.mail_domain is not None:
                mail_domain = _gs.mail_domain

    glitchtip_instances = glitchtip_instance_query(query_func=gqlapi.query).instances
    glitchtip_projects = (
        glitchtip_project_query(query_func=gqlapi.query).glitchtip_projects or []
    )

    for glitchtip_instance in glitchtip_instances:
        if instance and glitchtip_instance.name != instance:
            continue

        glitchtip_client = GlitchtipClient(
            host=glitchtip_instance.console_url,
            token=secret_reader.read_secret(glitchtip_instance.automation_token),
            read_timeout=read_timeout,
            max_retries=max_retries,
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
            mail_domain=mail_domain,
        )

        reconciler = GlitchtipReconciler(glitchtip_client, dry_run)
        reconciler.reconcile(current_state, desired_state)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    gqlapi = gql.get_api()
    return {
        "projects": gqlapi.query(GLITCHTIP_PROJECT_DEFINITION)["glitchtip_projects"],
        "instances": gqlapi.query(GLITCHTIP_INSTANCE_DEFINITION)["instances"],
    }
