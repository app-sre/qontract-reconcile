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
    for r in repos:
        is_admin, users = gl.get_project_users(r)
        if not is_admin:
            logging.error("'{}' is not shared with {} as 'Maintainer'".format(
                r, gl.user.username
            ))
            continue
