import logging

import reconcile.gql as gql
from reconcile.config import get_config
import utils.ldap_client as ldap_client
from utils.gitlab_api import GitLabApi


USERS_QUERY = """
{
  users {
    path
    redhat_username
  }
}
"""


def get_app_interface_gitlab_api():
    config = get_config()

    server = config['app-interface']['server']
    token = config['app-interface']['token']
    project_id = config['app-interface']['project_id']

    return GitLabApi(server, token, project_id, False)


def run(dry_run=False):
    gqlapi = gql.get_api()
    result = gqlapi.query(USERS_QUERY)

    if not dry_run:
        gl = get_app_interface_gitlab_api()

    for user in result['users']:
        username = user['redhat_username']
        path = 'data' + user['path']

        if ldap_client.user_exists(username):
            continue

        logging.info(['delete_user', username, path])

        if not dry_run:
            gl.create_delete_user_mr(username, path)
