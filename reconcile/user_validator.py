import sys
import logging

from utils.gpg import gpg_key_valid
import reconcile.queries as queries


QONTRACT_INTEGRATION = 'user-validator'


def validate_users_single_path(users):
    ok = True
    users_paths = {}
    for user in users:
        org_username = user['org_username']
        path = user['path']
        users_paths.setdefault(org_username, [])
        users_paths[org_username].append(path)

    users_with_multiple_paths = \
        [(u, p) for u, p in users_paths.items() if len(p) > 1]
    for u, p in users_with_multiple_paths:
        logging.error('user {} has multiple user files: {}'.format(u, p))
        ok = False

    return ok


def validate_users_gpg_key(users):
    ok = True
    for user in users:
        public_gpg_key = user.get('public_gpg_key')
        if public_gpg_key:
            gpg_ok, error_message = gpg_key_valid(public_gpg_key)
            if not gpg_ok:
                msg = \
                    'invalid public gpg key for user {}: {}'.format(
                        user['org_username'], error_message)
                logging.error(msg)
                ok = False

    return ok


def run(dry_run):
    users = queries.get_users()

    single_path_ok = validate_users_single_path(users)
    gpg_ok = validate_users_gpg_key(users)

    ok = single_path_ok and gpg_ok
    if not ok:
        sys.exit(1)
