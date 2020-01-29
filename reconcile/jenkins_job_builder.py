import sys
import logging

import utils.gql as gql
import reconcile.queries as queries

from utils.defer import defer
from utils.jjb_client import JJB


QUERY = """
{
  jenkins_configs: jenkins_configs_v1 {
    name
    instance {
      name
      serverUrl
      token {
        path
        field
      }
      deleteMethod
    }
    type
    config
    config_path
  }
}
"""


def init_jjb():
    gqlapi = gql.get_api()
    configs = gqlapi.query(QUERY)['jenkins_configs']
    settings = queries.get_app_interface_settings()
    return JJB(configs, ssl_verify=False, settings=settings)


def validate_repos_and_admins(jjb):
    jjb_repos = jjb.get_repos()
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in jjb_repos if r not in app_int_repos]
    for r in missing_repos:
        logging.error('repo is missing from codeComponents: {}'.format(r))
    jjb_admins = jjb.get_admins()
    app_int_users = queries.get_users()
    unknown_admins = [a for a in jjb_admins if a not in
                      [u['github_username'] for u in app_int_users]]
    for a in unknown_admins:
        logging.error('admin is missing from users: {}'.format(a))
    if missing_repos or unknown_admins:
        sys.exit(1)


@defer
def run(dry_run=False, io_dir='throughput/', compare=True, defer=None):
    jjb = init_jjb()
    defer(lambda: jjb.cleanup())
    if compare:
        validate_repos_and_admins(jjb)

    if dry_run:
        jjb.test(io_dir, compare=compare)
    else:
        jjb.update()
