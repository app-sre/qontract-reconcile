import logging
from multiprocessing.dummy import Pool as ThreadPool
from functools import partial

import utils.gql as gql
from utils.config import get_config
from utils.gitlab_api import GitLabApi


APPS_QUERY = """
{
  apps: apps_v1 {
    codeComponents {
        url
    }
  }
}
"""


def get_gitlab_repos(server):
    gqlapi = gql.get_api()
    apps = gqlapi.query(APPS_QUERY)['apps']

    code_components_lists = [a['codeComponents'] for a in apps
                             if a['codeComponents'] is not None]
    code_components = [item for sublist in code_components_lists
                       for item in sublist]
    repos = [c['url'] for c in code_components if c['url'].startswith(server)]

    return repos


def get_gitlab_api():
    config = get_config()

    gitlab_config = config['gitlab']
    server = gitlab_config['server']
    token = gitlab_config['token']

    return GitLabApi(server, token, ssl_verify=False)


def get_members_to_add(repo, gl, app_sre):
    maintainers = gl.get_project_maintainers(repo)
    if gl.user.username not in maintainers:
        logging.error("'{}' is not shared with {} as 'Maintainer'".format(
            repo, gl.user.username
        ))
        return []
    members_to_add = [{
        "user": u, "repo": repo} for u in app_sre
        if u.username not in maintainers]
    return members_to_add


def run(dry_run=False, thread_pool_size=10):
    gl = get_gitlab_api()
    repos = get_gitlab_repos(gl.server)
    app_sre = gl.get_app_sre_group_users()
    pool = ThreadPool(thread_pool_size)
    get_members_to_add_partial = \
        partial(get_members_to_add, gl=gl, app_sre=app_sre)
    results = pool.map(get_members_to_add_partial, repos)
    members_to_add = [item for sublist in results for item in sublist]
    for m in members_to_add:
        logging.info(['add_maintainer', m["user"], m["user"].username])
        if not dry_run:
            gl.add_project_member(m["repo"], m["user"])
