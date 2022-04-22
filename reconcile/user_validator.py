import os
import sys
import logging

from github.GithubException import GithubException
from requests.exceptions import ReadTimeout
from sretoolbox.utils import retry
from sretoolbox.utils import threaded

from reconcile import queries
from reconcile.utils.gpg import gpg_key_valid
from reconcile.github_users import init_github

GH_BASE_URL = os.environ.get("GITHUB_API", "https://api.github.com")
QONTRACT_INTEGRATION = "user-validator"


def validate_users_single_path(users):
    ok = True
    users_paths = {}
    for user in users:
        org_username = user["org_username"]
        path = user["path"]
        users_paths.setdefault(org_username, [])
        users_paths[org_username].append(path)

    users_with_multiple_paths = [(u, p) for u, p in users_paths.items() if len(p) > 1]
    for u, p in users_with_multiple_paths:
        logging.error("user {} has multiple user files: {}".format(u, p))
        ok = False

    return ok


def validate_users_gpg_key(users):
    ok = True
    for user in users:
        public_gpg_key = user.get("public_gpg_key")
        if public_gpg_key:
            try:
                gpg_key_valid(public_gpg_key)
            except ValueError as e:
                msg = "invalid public gpg key for user {}: {}".format(
                    user["org_username"], str(e)
                )
                logging.error(msg)
                ok = False

    return ok


@retry(exceptions=(GithubException, ReadTimeout))
def get_github_user(user, github):
    gh_user = github.get_user(user["github_username"])
    return user["org_username"], user["github_username"], gh_user.login


def validate_users_github(users, thread_pool_size):
    ok = True
    g = init_github()
    results = threaded.run(get_github_user, users, thread_pool_size, github=g)
    for org_username, gb_username, gh_login in results:
        if gb_username != gh_login:
            logging.error(
                "Github username is case sensitive in OSD. "
                f"User {org_username} is expecting to have "
                f"the github username of {gh_login}, "
                f"but the username specified in "
                f"app-interface is {gb_username}"
            )
            ok = False

    return ok


def run(dry_run, thread_pool_size=10):
    users = queries.get_users()

    single_path_ok = validate_users_single_path(users)
    gpg_ok = validate_users_gpg_key(users)
    github_ok = validate_users_github(users, thread_pool_size)

    ok = single_path_ok and gpg_ok and github_ok
    if not ok:
        sys.exit(1)
