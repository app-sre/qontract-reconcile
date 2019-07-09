import shutil
import yaml
import tempfile

import utils.gql as gql
import utils.vault_client as vault_client

from os import path

from jenkins_jobs.cli.entry import JenkinsJobs


QUERY = """
{
  jenkins_configs: jenkins_configs_v1 {
    path
    instance {
      name
      token {
        path
        field
      }
    }
    config
  }
}
"""


def collect_jenkins_configs():
    gqlapi = gql.get_api()
    configs = gqlapi.query(QUERY)['jenkins_configs']
    instances = {c['instance']['name']: c['instance']['token']
                 for c in configs}

    working_dirs = {}
    for name, token in instances.items():
        wd = tempfile.mkdtemp()
        ini = vault_client.read(token['path'], token['field'])
        ini_file_path = '{}/{}.ini'.format(wd, name)
        with open(ini_file_path, 'w') as f:
            f.write(ini)
        working_dirs[name] = wd

    configs.sort(key=sort_by_path)

    for c in configs:
        instance_name = c['instance']['name']
        config_file_path = \
            '{}/config.yaml'.format(working_dirs[instance_name])
        with open(config_file_path, 'a') as f:
            yaml.dump(yaml.load(c['config'], Loader=yaml.FullLoader), f)

    return working_dirs


def sort_by_path(config):
    return path.basename(config['path'])


def cleanup(working_dirs):
    for wd in working_dirs.values():
        shutil.rmtree(wd)


def run(dry_run=False):
    working_dirs = collect_jenkins_configs()
    for name, wd in working_dirs.items():
        ini_path = '{}/{}.ini'.format(wd, name)
        config_path = '{}/config.yaml'.format(wd)
        argv = ['--conf', ini_path, 'test', config_path]
        print(name)
        jjb = JenkinsJobs(argv)
        a = jjb.execute()
    cleanup(working_dirs)
