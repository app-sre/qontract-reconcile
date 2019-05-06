import logging

import utils.gql as gql
import utils.ldap_client as ldap_client

from utils.config import get_config
from utils.gitlab_api import GitLabApi

from multiprocessing.dummy import Pool as ThreadPool
from collections import defaultdict

QUERY = """
{
  users: users_v1 {
    path
    redhat_username
  }
}
"""


def init_users():
    gqlapi = gql.get_api()
    result = gqlapi.query(QUERY)['users']

    users = defaultdict(list)
    for user in result:
        u = user['redhat_username']
        p = 'data' + user['path']
        users[u].append(p)

    return [{ 'username': u, 'paths': p } for u, p in users.items()]


def get_app_interface_gitlab_api():
    config = get_config()

    server = config['app-interface']['server']
    token = config['app-interface']['token']
    project_id = config['app-interface']['project_id']

    return GitLabApi(server, token, project_id, False)


def init_user_spec(user):
    username = user['username']
    paths = user['paths']

    delete = False
    if not ldap_client.user_exists(username):
        delete = True

    return (username, delete, paths)


def run(dry_run=False, thread_pool_size=10):
    users = init_users()
    pool = ThreadPool(thread_pool_size)
    user_specs = pool.map(init_user_spec, users)
    users_to_delete = [(username, paths) for username, delete, paths
                       in user_specs if delete]
    import sys
    print(users_to_delete)
    sys.exit()

    if not dry_run:
        gl = get_app_interface_gitlab_api()

    for username, paths in users_to_delete:
        logging.info(['delete_user', username])

        if not dry_run:
            gl.create_delete_user_mr(username, paths)
