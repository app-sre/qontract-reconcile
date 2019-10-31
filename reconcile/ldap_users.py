import sys
import logging

import utils.gql as gql
import utils.threaded as threaded
import utils.ldap_client as ldap_client
import reconcile.queries as queries

from utils.gitlab_api import GitLabApi

from collections import defaultdict

QUERY = """
{
  users: users_v1 {
    path
    org_username
  }
}
"""


def init_users():
    gqlapi = gql.get_api()
    result = gqlapi.query(QUERY)['users']

    users = defaultdict(list)
    for user in result:
        u = user['org_username']
        p = 'data' + user['path']
        users[u].append(p)

    return [{'username': username, 'paths': paths}
            for username, paths in users.items()]


def init_user_spec(user):
    username = user['username']
    paths = user['paths']

    delete = False
    if not ldap_client.user_exists(username):
        delete = True

    return (username, delete, paths)


def validate_users_single_path(users):
    ok = True
    users_with_multiple_paths = [(user['username'], user['paths']) for user
                                 in users if len(user['paths']) > 1]
    for u, p in users_with_multiple_paths:
        logging.error('user {} has multiple user files: {}'.format(u, p))
        ok = False

    return ok


def run(gitlab_project_id, dry_run=False, thread_pool_size=10):
    users = init_users()
    user_specs = threaded.run(init_user_spec, users, thread_pool_size)
    users_to_delete = [(username, paths) for username, delete, paths
                       in user_specs if delete]

    if not dry_run:
        instance = queries.get_gitlab_instance()
        gl = GitLabApi(instance, project_id=gitlab_project_id)

    for username, paths in users_to_delete:
        logging.info(['delete_user', username])

        if not dry_run:
            gl.create_delete_user_mr(username, paths)

    if not validate_users_single_path(users):
        sys.exit(1)
