import sys
import json
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


def get_openshift_saas_deploy_job_name(saas_file_name, env_name, settings):
    job_template_name = settings['saasDeployJobTemplate']
    return f"{job_template_name}-{saas_file_name}-{env_name}"


def collect_saas_file_configs():
    # collect a list of jobs per saas file per environment.
    # each saas_file_config should have the structure described
    # in the above query.
    # to make things understandable, each variable used to form
    # the structure will be called `jc_<variable>` (jenkins config).
    saas_file_configs = []
    saas_files = queries.get_saas_files()
    settings = queries.get_app_interface_settings()
    for saas_file in saas_files:
        saas_file_name = saas_file['name']
        jc_instance = saas_file['instance']
        # currently ignoring the actual Slack workspace
        # as that is configured in Jenkins.
        # revisit this if we support more then a single Slack workspace.
        slack_channel = saas_file['slack']['channel']
        for resource_template in saas_file['resourceTemplates']:
            for target in resource_template['targets']:
                namespace = target['namespace']
                env_name = namespace['environment']['name']
                upstream = target.get('upstream', '')
                job_template_name = settings['saasDeployJobTemplate']
                if upstream:
                    job_template_name += '-with-upstream'
                app_name = namespace['app']['name']
                jc_name = get_openshift_saas_deploy_job_name(
                    saas_file_name, env_name, settings)
                existing_configs = \
                    [c for c in saas_file_configs if c['name'] == jc_name]
                if existing_configs:
                    continue

                # each config is a list with a single item
                # with the following structure:
                # project:
                #   name: 'openshift-saas-deploy-{saas_file_name}-{env_name}'
                #   saas_file_name: '{saas_file_name}'
                #   env_name: '{env_name}'
                #   app_name: '{app_name}'
                #   slack_channel: '{slack_channel}'
                #   jobs:
                #   - 'openshift-saas-deploy':
                #       display_name: display name of the job
                jc_config = json.dumps([{
                    'project': {
                        'name': jc_name,
                        'saas_file_name': saas_file_name,
                        'env_name': env_name,
                        'app_name': app_name,
                        'slack_channel': slack_channel,
                        'upstream': upstream,
                        'jobs': [{
                            job_template_name: {
                                'display_name': jc_name
                            }
                        }]
                    }
                }])
                saas_file_configs.append({
                    'name': jc_name,
                    'instance': jc_instance,
                    'type': 'jobs',
                    'config': jc_config
                })

    return saas_file_configs, settings


def collect_configs():
    gqlapi = gql.get_api()
    raw_jjb_configs = gqlapi.query(QUERY)['jenkins_configs']
    saas_file_configs, settings = collect_saas_file_configs()
    configs = raw_jjb_configs + saas_file_configs

    return configs, settings


def init_jjb():
    configs, settings = collect_configs()
    return JJB(configs, ssl_verify=False, settings=settings)


def validate_repos_and_admins(jjb):
    jjb_repos = jjb.get_repos()
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in jjb_repos if r not in app_int_repos]
    for r in missing_repos:
        logging.error('repo is missing from codeComponents: {}'.format(r))
    jjb_admins = jjb.get_admins()
    app_int_users = queries.get_users()
    app_int_bots = queries.get_bots()
    github_usernames = \
        [u.get('github_username') for u in app_int_users] + \
        [b.get('github_username') for b in app_int_bots]
    unknown_admins = [a for a in jjb_admins if a not in github_usernames]
    for a in unknown_admins:
        logging.warning('admin is missing from users: {}'.format(a))
    if missing_repos:
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
