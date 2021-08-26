import logging

from collections import defaultdict

import reconcile.queries as queries
import reconcile.utils.ldap_client as ldap_client

from reconcile import mr_client_gateway
from reconcile.utils.mr import CreateDeleteUser


QONTRACT_INTEGRATION = 'ldap-users'


def init_users():
    app_int_users = queries.get_users(refs=True)

    users = defaultdict(set)
    for user in app_int_users:
        u = user['org_username']
        p = 'data' + user['path']
        users[u].add(p)
        for r in user.get('requests'):
            users[u].add('data' + r['path'])
        for q in user.get('queries'):
            users[u].add('data' + q['path'])

    return [{'username': username, 'paths': paths}
            for username, paths in users.items()]


def run(dry_run, gitlab_project_id=None):
    users = init_users()
    ldap_users = ldap_client.get_users([u['username'] for u in users])
    users_to_delete = [u for u in users if u['username'] not in ldap_users]

    if not dry_run:
        mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id,
                                        sqs_or_gitlab='gitlab')

    for u in users_to_delete:
        username = u['username']
        paths = u['paths']
        logging.info(['delete_user', username])

        if not dry_run:
            mr = CreateDeleteUser(username, paths)
            mr.submit(cli=mr_cli)
