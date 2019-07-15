import utils.gql as gql

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


def run(dry_run=False, io_dir='throughput/', compare=True):
    jjb = init_jjb()

    if dry_run:
        jjb.test(io_dir, compare=compare)
    else:
        jjb.update()

    jjb.cleanup()
