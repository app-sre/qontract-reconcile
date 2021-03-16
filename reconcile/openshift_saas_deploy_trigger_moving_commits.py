import sys
import logging


import reconcile.jenkins_plugins as jenkins_base
import reconcile.queries as queries

from reconcile.jenkins_job_builder import get_openshift_saas_deploy_job_name
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-moving-commits'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(dry_run, thread_pool_size=10):
    saas_files = queries.get_saas_files()
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(1)

    # Remove saas-file targets that are disabled
    for saas_file in saas_files[:]:
        resource_templates = saas_file['resourceTemplates']
        for rt in resource_templates[:]:
            targets = rt['targets']
            for target in targets[:]:
                if target['disable']:
                    targets.remove(target)

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

    trigger_specs = saasherder.get_moving_commits_diff(dry_run)
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
            try:
                if job_name not in already_triggered:
                    jenkins.trigger_job(job_name)
                    already_triggered.append(job_name)
                saasherder.update_moving_commit(job_spec)
            except Exception:
                error = True
                logging.error(
                    f"could not trigger job {job_name} in {instance_name}.")

    if error:
        sys.exit(1)
