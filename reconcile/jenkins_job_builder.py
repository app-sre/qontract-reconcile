import os
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
    name
    instance {
      name
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


class FetchResourceError(Exception):
    def __init__(self, msg):
        super(FetchResourceError, self).__init__(
            "error fetching resource: " + str(msg)
        )


def collect_jenkins_configs():
    gqlapi = gql.get_api()
    configs = gqlapi.query(QUERY)['jenkins_configs']
    instances = {c['instance']['name']: c['instance']['token']
                 for c in configs}

    working_dirs = {}
    for name, token in instances.items():
        wd = tempfile.mkdtemp()
        ini = vault_client.read(token['path'], token['field'])
        ini = ini.replace('"', '')
        ini = ini.replace('false', 'False')
        ini_file_path = '{}/{}.ini'.format(wd, name)
        with open(ini_file_path, 'w') as f:
            f.write(ini)
            f.write('\n')
        working_dirs[name] = wd

    sort(configs)

    for c in configs:
        instance_name = c['instance']['name']
        config = c['config']
        config_file_path = \
            '{}/config.yaml'.format(working_dirs[instance_name])
        if config:
            with open(config_file_path, 'a') as f:
                yaml.dump(yaml.load(config, Loader=yaml.FullLoader), f)
                f.write('\n')
        else:
            config_path = c['config_path']
            # get config data
            try:
                config_resource = gqlapi.get_resource(config_path)
                config = config_resource['content']
            except gql.GqlApiError as e:
                raise FetchResourceError(e.message)
            with open(config_file_path, 'a') as f:
                f.write(config)
                f.write('\n')

    return working_dirs


def sort(configs):
    configs.sort(key=sort_by_name)
    configs.sort(key=sort_by_type)


def sort_by_type(config):
    if config['type'] == 'common':
        return 00
    elif config['type'] == 'views':
        return 10
    elif config['type'] == 'secrets':
        return 20
    elif config['type'] == 'job-templates':
        return 30
    elif config['type'] == 'jobs':
        return 40


def sort_by_name(config):
    return config['name']


def cleanup(working_dirs):
    for wd in working_dirs.values():
        shutil.rmtree(wd)


def run(dry_run=False):
    working_dirs = collect_jenkins_configs()
    for name, wd in working_dirs.items():
        ini_path = '{}/{}.ini'.format(wd, name)
        config_path = '{}/config.yaml'.format(wd)

        if not dry_run:
            os.environ['PYTHONHTTPSVERIFY'] = '0'
            argv = ['--conf', ini_path, 'update', config_path]
            jjb = JenkinsJobs(argv)
            a = jjb.execute()

    cleanup(working_dirs)
