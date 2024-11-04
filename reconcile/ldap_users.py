import logging
from collections import defaultdict

from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.utils import gql
from reconcile.utils.defer import defer
from reconcile.utils.ldap_client import LdapClient
from reconcile.utils.mr import (
    CreateDeleteUserAppInterface,
    CreateDeleteUserInfra,
)
from reconcile.utils.mr.user_maintenance import PathTypes

QONTRACT_INTEGRATION = "ldap-users"


def init_users() -> list[dict[str, list]]:
    app_int_users = queries.get_users(refs=True)

    users = defaultdict(list)
    for user in app_int_users:
        u = user["org_username"]
        item = {"type": PathTypes.USER, "path": "data" + user["path"]}
        users[u].append(item)
        for r in user.get("requests"):
            item = {"type": PathTypes.REQUEST, "path": "data" + r["path"]}
            users[u].append(item)
        for q in user.get("queries"):
            item = {"type": PathTypes.QUERY, "path": "data" + q["path"]}
            users[u].append(item)
        for g in user.get("gabi_instances"):
            item = {"type": PathTypes.GABI, "path": "data" + g["path"]}
            users[u].append(item)
        for a in user.get("aws_accounts", []):
            item = {"type": PathTypes.AWS_ACCOUNTS, "path": "data" + a["path"]}
            users[u].append(item)
        for s in user.get("schedules"):
            item = {"type": PathTypes.SCHEDULE, "path": "data" + s["path"]}
            users[u].append(item)

    return [{"username": username, "paths": paths} for username, paths in users.items()]


LDAP_SETTINGS_QUERY = """
{
  settings: app_interface_settings_v1 {
    ldap {
      serverUrl
      baseDn
    }
  }
}
"""


def get_ldap_settings() -> dict:
    """Returns LDAP settings"""
    gqlapi = gql.get_api()
    settings = gqlapi.query(LDAP_SETTINGS_QUERY)["settings"]
    if settings:
        # assuming a single settings file for now
        return settings[0]
    raise ValueError("no app-interface-settings settings found")


@defer
def run(dry_run, app_interface_project_id, infra_project_id, defer=None):
    users = init_users()
    with LdapClient.from_settings(get_ldap_settings()) as ldap_client:
        ldap_users = ldap_client.get_users([u["username"] for u in users])

    users_to_delete = [u for u in users if u["username"] not in ldap_users]

    if not dry_run:
        mr_cli_app_interface = mr_client_gateway.init(
            gitlab_project_id=app_interface_project_id, sqs_or_gitlab="gitlab"
        )
        defer(mr_cli_app_interface.cleanup)
        mr_cli_infra = mr_client_gateway.init(
            gitlab_project_id=infra_project_id, sqs_or_gitlab="gitlab"
        )
        defer(mr_cli_infra.cleanup)

    for u in users_to_delete:
        username = u["username"]
        paths = u["paths"]
        logging.info(["delete_user", username])

        if not dry_run:
            mr = CreateDeleteUserAppInterface(username, paths)
            mr.submit(cli=mr_cli_app_interface)

    if not dry_run:
        usernames = [u["username"] for u in users_to_delete]
        mr_infra = CreateDeleteUserInfra(usernames)
        mr_infra.submit(cli=mr_cli_infra)
