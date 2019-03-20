import logging

import utils.gql as gql
import utils.ldap_client as ldap_client

from utils.config import get_config
from utils.gitlab_api import GitLabApi

from multiprocessing.dummy import Pool as ThreadPool

USERS_QUERY = """
{
  users: users_v1 {
    path
    redhat_username
  }
}
"""


class UserSpec(object):
    def __init__(self, delete, username, path):
        self.delete = delete
        self.username = username
        self.path = path


def get_app_interface_gitlab_api():
    config = get_config()

    server = config['app-interface']['server']
    token = config['app-interface']['token']
    project_id = config['app-interface']['project_id']

    return GitLabApi(server, token, project_id, False)


def init_user_spec(user):
    username = user['redhat_username']
    path = 'data' + user['path']

    delete = False
    if not ldap_client.user_exists(username):
        delete = True

    return UserSpec(delete, username, path)


def run(dry_run=False, thread_pool_size=10):
    gqlapi = gql.get_api()
    result = gqlapi.query(USERS_QUERY)

    if not dry_run:
        gl = get_app_interface_gitlab_api()

    pool = ThreadPool(thread_pool_size)
    user_specs = pool.map(init_user_spec, result['users'])
    users_to_delete = [u for u in user_specs if u.delete]

    for u in users_to_delete:
        logging.info(['delete_user', u.username, u.path])

        if not dry_run:
            gl.create_delete_user_mr(u.username, u.path)
