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
    return JJB(configs, ssl_verify=False)


def validate_repos(jjb):
    jjb_repos = jjb.get_repos()
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in jjb_repos if r not in app_int_repos]
    for r in set(missing_repos):
        logging.error('repo is missing from codeComponents: {}'.format(r))
    if missing_repos:
        sys.exit(1)


@defer
def run(dry_run=False, io_dir='throughput/', compare=True, defer=None):
    jjb = init_jjb()
    defer(lambda: jjb.cleanup())
    if compare:
        validate_repos(jjb)

    if dry_run:
        jjb.test(io_dir, compare=compare)
    else:
        jjb.update()
