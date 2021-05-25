import logging
import sys
import time


import reconcile.queries as queries
import reconcile.jenkins_plugins as jenkins_base
import reconcile.openshift_saas_deploy_trigger_base as osdt_base

from reconcile.utils.semver_helper import make_semver
from reconcile.utils.gitlab_api import GitLabApi
from reconcile.utils.saasherder import SaasHerder


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-configs'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(dry_run, thread_pool_size=10):
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

    trigger_specs = saasherder.get_configs_diff()
    already_triggered = []

    error = True  # enter loop
    while error:
        error = False
        for job_spec in trigger_specs:
            trigger_options = {
                'dry_run': dry_run,
                'spec': job_spec,
                'jenkins_map': jenkins_map,
                'already_triggered': already_triggered,
                'settings': settings,
                'state_update_method': saasherder.update_config,
            }
            trigger_error = osdt_base.trigger(trigger_options)
            if trigger_error:
                error = True

        if error:
            time.sleep(10)  # add to contants module once created
