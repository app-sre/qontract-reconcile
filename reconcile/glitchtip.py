from typing import Iterable

from rich import print

from reconcile import queries
from reconcile.gql_definitions.glitchtip import glitchtip_instance
from reconcile.utils import gql
from reconcile.utils.glitchtip.client import GlitchtipClient, User
from reconcile.utils.secret_reader import SecretReader

QONTRACT_INTEGRATION = "glitchtip"


def filter_users(users: Iterable[User], ignore_users: Iterable[str]) -> list[User]:
    return [user for user in users if user.email not in ignore_users]


def fetch_current_state(glitchtip_client: GlitchtipClient, ignore_users: Iterable[str]):
    orgs = glitchtip_client.organizations()
    for org in orgs:
        org.teams = glitchtip_client.teams(org=org)
        org.projects = glitchtip_client.projects(org=org)
        org.users = filter_users(
            glitchtip_client.organization_users(org=org), ignore_users
        )
        for team in org.teams:
            team.users = filter_users(
                glitchtip_client.team_users(org=org, team=team), ignore_users
            )
    print(orgs)


def run(dry_run):
    gqlapi = gql.get_api()
    # github = init_github()
    secret_reader = SecretReader(queries.get_secret_reader_settings())
    instances = glitchtip_instance.query(query_func=gqlapi.query).instances
    for instance in instances:
        glitchtip_client = GlitchtipClient(
            host=instance.console_url,
            token=secret_reader.read(
                {
                    "path": instance.automation_token.path,
                    "field": instance.automation_token.field,
                    "format": instance.automation_token.q_format,
                    "version": instance.automation_token.version,
                }
            ),
        )
        current_state = fetch_current_state(
            glitchtip_client, ignore_users=[instance.automation_user_email]
        )
        # desired_state = fetch_desired_state(gqlapi, instance, github)

        # reconciler = SentryReconciler(sentry_client, dry_run)
        # reconciler.reconcile(current_state, desired_state)

    # fetch_current_state()
    # print(query_data)


# def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
#     gqlapi = gql.get_api()
#     return {
#         "roles": gqlapi.query(SENTRY_USERS_QUERY)["roles"],
#         "teams": gqlapi.query(SENTRY_TEAMS_QUERY)["teams"],
#         "apps": gqlapi.query(SENTRY_PROJECTS_QUERY)["apps"],
#         "instances": gqlapi.query(SENTRY_INSTANCES_QUERY)["instances"],
#     }
