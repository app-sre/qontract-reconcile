import logging
from collections import defaultdict

from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.utils import gql
from reconcile.utils.ldap_client import LdapClient
from reconcile.utils.mr import CreateDeleteUser
from reconcile.utils.mr.user_maintenance import PathTypes

QONTRACT_INTEGRATION = "ldap-users"


def init_users():
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
    else:
        raise ValueError("no app-interface-settings settings found")


def run(dry_run, gitlab_project_id=None):
    users = init_users()
    with LdapClient.from_settings(get_ldap_settings()) as ldap_client:
        ldap_users = ldap_client.get_users([u["username"] for u in users])

    users_to_delete = [u for u in users if u["username"] not in ldap_users]

    if not dry_run:
        mr_cli = mr_client_gateway.init(
            gitlab_project_id=gitlab_project_id, sqs_or_gitlab="gitlab"
        )

    for u in users_to_delete:
        username = u["username"]
        paths = u["paths"]
        logging.info(["delete_user", username])

        if not dry_run:
            mr = CreateDeleteUser(username, paths)
            mr.submit(cli=mr_cli)
