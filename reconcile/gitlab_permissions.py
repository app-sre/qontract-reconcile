import sys
import logging

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


def run(dry_run=False):
    gl = get_gitlab_api()
    repos = get_gitlab_repos(gl.server)
    app_sre = gl.get_app_sre_group_users()
    error = False
    for r in repos:
        maintainers = gl.get_project_maintainers(r)
        if gl.user.username not in maintainers:
            error = True
            logging.error("'{}' is not shared with {} as 'Maintainer'".format(
                r, gl.user.username
            ))
            continue
        members_to_add = [u for u in app_sre
                          if u.username not in maintainers]
        for m in members_to_add:
            logging.info(['add_maintainer', r, m.username])

            if not dry_run:
                gl.add_project_member(r, m)

    sys.exit(error)
