from functools import cache
from typing import Iterable, Optional, Sequence

from github import Github, UnknownObjectException
from reconcile import queries

# TODO: init_github must be move into a utils module
from reconcile.github_users import init_github
from reconcile.glitchtip.reconciler import GlitchtipReconciler
from reconcile.gql_definitions.glitchtip.glitchtip_instance import (
    query as glitchtip_instance_query,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    GlitchtipProjectsV1,
    RoleV1,
)
from reconcile.gql_definitions.glitchtip.glitchtip_project import (
    query as glitchtip_project_query,
)
from reconcile.utils import gql
from reconcile.utils.glitchtip import GlitchtipClient, Organization, Project, Team, User
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


@cache
def github_email(gh: Github, github_username: str) -> Optional[str]:
    try:
        return gh.get_user(login=github_username).email
    except UnknownObjectException:
        return None


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
            team.users = filter_users(
                glitchtip_client.team_users(
                    organization_slug=organization.slug, team_slug=team.slug
                ),
                ignore_users,
            )
    return organizations


def fetch_desired_state(
    glitchtip_projects: Sequence[GlitchtipProjectsV1],
    gh: Github,
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
        for glitchtip_team in glitchtip_project.teams:
            users: list[User] = []
            for role in glitchtip_team.roles:
                for role_user in role.users:
                    if not (
                        email := github_email(
                            gh=gh, github_username=role_user.github_username
                        )
                    ):
                        # TODO must be configurable
                        email = role_user.org_username + "@redhat.com"
                    users.append(
                        User(
                            email=email,
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
    return [org for org in organizations.values()]


def run(dry_run):
    gqlapi = gql.get_api()
    github = init_github()
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    glitchtip_instances = glitchtip_instance_query(query_func=gqlapi.query).instances
    glitchtip_projects: list[GlitchtipProjectsV1] = []
    for app in glitchtip_project_query(query_func=gqlapi.query).apps or []:
        glitchtip_projects += app.glitchtip_projects if app.glitchtip_projects else []

    for glitchtip_instance in glitchtip_instances:
        glitchtip_client = GlitchtipClient(
            host=glitchtip_instance.console_url,
            token=secret_reader.read(
                {
                    "path": glitchtip_instance.automation_token.path,
                    "field": glitchtip_instance.automation_token.field,
                    "format": glitchtip_instance.automation_token.q_format,
                    "version": glitchtip_instance.automation_token.version,
                }
            ),
        )
        current_state = fetch_current_state(
            glitchtip_client=glitchtip_client,
            ignore_users=[glitchtip_instance.automation_user_email],
        )
        desired_state = fetch_desired_state(
            glitchtip_projects=[
                p
                for p in glitchtip_projects
                if p.organization.instance.name == glitchtip_instance.name
            ],
            gh=github,
        )

        reconciler = GlitchtipReconciler(glitchtip_client, dry_run)
        reconciler.reconcile(current_state, desired_state)


# def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
#     gqlapi = gql.get_api()
#     return {
#         "roles": gqlapi.query(SENTRY_USERS_QUERY)["roles"],
#         "teams": gqlapi.query(SENTRY_TEAMS_QUERY)["teams"],
#         "apps": gqlapi.query(SENTRY_PROJECTS_QUERY)["apps"],
#         "instances": gqlapi.query(SENTRY_INSTANCES_QUERY)["instances"],
#     }
