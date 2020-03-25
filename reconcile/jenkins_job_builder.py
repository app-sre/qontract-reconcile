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
    if missing_repos:
        msg = 'repos are missing from codeComponents: ' + missing_repos
        raise Exception(msg)
    jjb_admins = jjb.get_admins()
    app_int_users = queries.get_users()
    app_int_bots = queries.get_bots()
    github_usernames = \
        [u.get('github_username') for u in app_int_users] + \
        [b.get('github_username') for b in app_int_bots]
    unknown_admins = [a for a in jjb_admins if a not in github_usernames]
    if unknown_admins:
        logging.warning('user file not found for: {}'.format(unknown_admins))


@defer
def run(dry_run=False, io_dir='throughput/', compare=True, defer=None):
    jjb = init_jjb()
    defer(lambda: jjb.cleanup())

    try:
        if compare:
            validate_repos_and_admins(jjb)
        if dry_run:
            jjb.test(io_dir, compare=compare)
        else:
            jjb.update()
    except Exception as e:
        msg = 'Error running integration. '
        msg += 'Exception: {}'
        msg = msg.format(str(e))
        logging.error(msg)
        sys.exit(1)
