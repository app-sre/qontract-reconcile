import sys
import json
import logging

import reconcile.utils.gql as gql
import reconcile.queries as queries

from reconcile.utils.defer import defer
from reconcile.utils.jjb_client import JJB
from reconcile.utils.state import State


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

QONTRACT_INTEGRATION = 'jenkins-job-builder'
GENERATE_TYPE = ['jobs', 'views']


def get_openshift_saas_deploy_job_name(saas_file_name, env_name, settings):
    job_template_name = settings['saasDeployJobTemplate']
    return f"{job_template_name}-{saas_file_name}-{env_name}"


def collect_saas_file_configs(settings, instance_name=None):
    # collect a list of jobs per saas file per environment.
    # each saas_file_config should have the structure described
    # in the above query.
    # to make things understandable, each variable used to form
    # the structure will be called `jc_<variable>` (jenkins config).
    saas_file_configs = []
    repo_urls = set()
    saas_files = queries.get_saas_files()
    job_template_name = settings['saasDeployJobTemplate']
    for saas_file in saas_files:
        saas_file_name = saas_file['name']
        jc_instance = saas_file['instance']
        if instance_name is not None and jc_instance['name'] != instance_name:
            continue
        app_name = saas_file['app']['name']
        # currently ignoring the actual Slack workspace
        # as that is configured in Jenkins.
        # revisit this if we support more then a single Slack workspace.
        output = saas_file['slack'].get('output') or 'publish'
        # if the output type is 'publish', we send notifications
        # to the selected slack_channel
        slack_channel = \
            saas_file['slack']['channel'] \
            if output == 'publish' \
            else 'dev-null'
        slack_notify_start = False
        slack_notifications = saas_file['slack'].get('notifications')
        if slack_notifications:
            start = slack_notifications.get('start')
            if start:
                slack_notify_start = True
        timeout = saas_file.get('timeout', None)
        for resource_template in saas_file['resourceTemplates']:
            url = resource_template['url']
            repo_urls.add(url)
            for target in resource_template['targets']:
                env_name = target['namespace']['environment']['name']
                upstream = target.get('upstream') or ''
                final_job_template_name = \
                    f'{job_template_name}-with-upstream' if upstream \
                    else job_template_name

                jc_name = get_openshift_saas_deploy_job_name(
                    saas_file_name, env_name, settings)
                existing_configs = \
                    [c for c in saas_file_configs if c['name'] == jc_name]
                if existing_configs:
                    # if upstream is defined - append it to existing upstreams
                    if upstream:
                        # should be exactly one
                        jc_data = existing_configs[0]['data']
                        project = jc_data['project']
                        # append upstream to existing upstreams
                        project['upstream'] += f',{upstream}'
                        # update job template name if needed
                        job_definition = project['jobs'][0]
                        if job_template_name in job_definition:
                            job_definition[final_job_template_name] = \
                                job_definition.pop(job_template_name)
                    continue

                # each config is a list with a single item
                # with the following structure:
                # project:
                #   name: 'openshift-saas-deploy-{saas_file_name}-{env_name}'
                #   saas_file_name: '{saas_file_name}'
                #   env_name: '{env_name}'
                #   app_name: '{app_name}'
                #   slack_channel: '{slack_channel}'
                #   slack_notify_start: '{slack_notify_start}
                #   jobs:
                #   - 'openshift-saas-deploy':
                #       display_name: display name of the job
                jc_data = {
                    'project': {
                        'name': jc_name,
                        'saas_file_name': saas_file_name,
                        'env_name': env_name,
                        'app_name': app_name,
                        'slack_channel': slack_channel,
                        'slack_notify_start': slack_notify_start,
                        'upstream': upstream,
                        'jobs': [{
                            final_job_template_name: {
                                'display_name': jc_name
                            }
                        }]
                    }
                }
                if timeout:
                    jc_data['project']['timeout'] = timeout
                saas_file_configs.append({
                    'name': jc_name,
                    'instance': jc_instance,
                    'type': 'jobs',
                    'data': jc_data
                })

    for saas_file_config in saas_file_configs:
        jc_data = saas_file_config.pop('data')
        saas_file_config['config'] = json.dumps([jc_data])

    return saas_file_configs, repo_urls


def collect_configs(instance_name, config_name, settings):
    gqlapi = gql.get_api()
    raw_jjb_configs = gqlapi.query(QUERY)['jenkins_configs']
    if instance_name is not None:
        raw_jjb_configs = [n for n in raw_jjb_configs
                           if n['instance']['name'] == instance_name]
    if config_name is not None:
        raw_jjb_configs = [n for n in raw_jjb_configs
                           if n['type'] not in GENERATE_TYPE
                           or n['name'] == config_name]
        if not raw_jjb_configs:
            raise ValueError(f"config name {config_name} is not found")
        return raw_jjb_configs, {}
    saas_file_configs, saas_file_repo_urls = \
        collect_saas_file_configs(settings, instance_name)
    configs = raw_jjb_configs + saas_file_configs
    if not configs:
        raise ValueError(f"instance name {instance_name} is not found")
    return configs, saas_file_repo_urls


def init_jjb(instance_name=None, config_name=None, print_only=False):
    settings = queries.get_app_interface_settings()
    configs, additional_repo_urls = \
        collect_configs(instance_name, config_name, settings)
    return JJB(configs, ssl_verify=False,
               settings=settings, print_only=print_only), \
        additional_repo_urls


def validate_repos_and_admins(jjb, additional_repo_urls):
    jjb_repos = jjb.get_repos()
    jjb_repos.update(additional_repo_urls)
    app_int_repos = queries.get_repos()
    missing_repos = [r for r in jjb_repos if r not in app_int_repos]
    for r in missing_repos:
        logging.error('repo is missing from codeComponents: {}'.format(r))
    jjb_admins = jjb.get_admins()
    app_int_users = queries.get_users()
    app_int_bots = queries.get_bots()
    external_users = queries.get_external_users()
    github_usernames = \
        [u.get('github_username') for u in app_int_users] + \
        [b.get('github_username') for b in app_int_bots] + \
        [u.get('github_username') for u in external_users]
    unknown_admins = [a for a in jjb_admins if a not in github_usernames]
    for a in unknown_admins:
        logging.warning('admin is missing from users: {}'.format(a))
    if missing_repos:
        sys.exit(1)


@defer
def run(dry_run, io_dir='throughput/', print_only=False,
        config_name=None, job_name=None, instance_name=None, defer=None):
    if not print_only and config_name is not None:
        raise Exception("--config-name must works with --print-only mode")
    jjb, additional_repo_urls = \
        init_jjb(instance_name, config_name, print_only)
    defer(lambda: jjb.cleanup())

    if print_only:
        jjb.print_jobs(job_name=job_name)
        if config_name is not None:
            jjb.generate(io_dir, 'printout')
        sys.exit(0)

    accounts = queries.get_aws_accounts()
    state = State(
        integration=QONTRACT_INTEGRATION,
        accounts=accounts,
        settings=jjb.settings
    )

    if dry_run:
        validate_repos_and_admins(jjb, additional_repo_urls)
        jjb.generate(io_dir, 'desired')
        jjb.overwrite_configs(state)
        jjb.generate(io_dir, 'current')
        jjb.print_diffs(io_dir, instance_name)
    else:
        jjb.update()
        configs = jjb.get_configs()
        for name, desired_config in configs.items():
            state.add(name, value=desired_config, force=True)
