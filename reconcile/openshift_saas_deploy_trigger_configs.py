import sys
import semver
import logging

import reconcile.queries as queries
import reconcile.jenkins_plugins as jenkins_base

from utils.gitlab_api import GitLabApi
from utils.saasherder import SaasHerder
from reconcile.jenkins_job_builder import get_openshift_saas_deploy_job_name


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-configs'
QONTRACT_INTEGRATION_VERSION = semver.format_version(0, 1, 0)


def run(dry_run=False, thread_pool_size=10):
    saas_files = queries.get_saas_files()
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(1)

    instance = queries.get_gitlab_instance()
    settings = queries.get_app_interface_settings()
    accounts = queries.get_aws_accounts()
    gl = GitLabApi(instance, settings=settings)
    jenkins_map = jenkins_base.get_jenkins_map()

    saasherder = SaasHerder(
        saas_files,
        thread_pool_size=thread_pool_size,
        gitlab=gl,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        settings=settings,
        accounts=accounts)
    if not saasherder.valid:
        sys.exit(1)

    trigger_specs = saasherder.get_configs_diff()
    already_triggered = []
    error = False
    for job_spec in trigger_specs:
        saas_file_name = job_spec['saas_file_name']
        env_name = job_spec['env_name']
        instance_name = job_spec['instance_name']
        job_name = get_openshift_saas_deploy_job_name(
            saas_file_name, env_name, settings)
        if job_name not in already_triggered:
            logging.info(['trigger_job', instance_name, job_name])
            if dry_run:
                already_triggered.append(job_name)

        if not dry_run:
            jenkins = jenkins_map[instance_name]
            upstream = job_spec['target_config'].get('upstream')
            if upstream and jenkins.is_job_running(upstream):
                # if upstream job is defined and it is currently running,
                # triggering the job may result in an image that was not
                # built yet. we can skip triggering this job since it will
                # be triggered when the upstream job succeeds. if it fails,
                # we are better off not attempting to deploy. tl;dr - we
                # skip triggering a job that it's upstream job is running.
                # we use already_triggered even though the job was not
                # triggered, but this will achieve the desired outcome.
                already_triggered.append(job_name)
            try:
                if job_name not in already_triggered:
                    jenkins.trigger_job(job_name)
                    already_triggered.append(job_name)
                saasherder.update_config(job_spec)
            except Exception:
                error = True
                logging.error(
                    f"could not trigger job {job_name} in {instance_name}.")

    if error:
        sys.exit(1)
