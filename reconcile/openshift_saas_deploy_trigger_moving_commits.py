import sys
import logging

import reconcile.openshift_saas_deploy_trigger_base as osdt_base
import reconcile.queries as queries

from reconcile.status import ExitCodes
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-moving-commits'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    saas_files = queries.get_saas_files(v1=True, v2=True)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(ExitCodes.ERROR)

    # Remove saas-file targets that are disabled
    for saas_file in saas_files[:]:
        resource_templates = saas_file['resourceTemplates']
        for rt in resource_templates[:]:
            targets = rt['targets']
            for target in targets[:]:
                if target['disable']:
                    targets.remove(target)

    setup_options = {
        'saas_files': saas_files,
        'thread_pool_size': thread_pool_size,
        'internal': internal,
        'use_jump_host': use_jump_host,
        'integration': QONTRACT_INTEGRATION,
        'integration_version': QONTRACT_INTEGRATION_VERSION,
    }
    saasherder, jenkins_map, oc_map, settings = osdt_base.setup(setup_options)
    defer(lambda: oc_map.cleanup())

    trigger_specs = saasherder.get_moving_commits_diff(dry_run)
    already_triggered = []
    error = False
    for job_spec in trigger_specs:
        trigger_options = {
            'dry_run': dry_run,
            'spec': job_spec,
            'jenkins_map': jenkins_map,
            'oc_map': oc_map,
            'already_triggered': already_triggered,
            'settings': settings,
            'state_update_method': saasherder.update_moving_commit,
            'integration': QONTRACT_INTEGRATION,
            'integration_version': QONTRACT_INTEGRATION_VERSION,
        }
        trigger_error = osdt_base.trigger(trigger_options)
        if trigger_error:
            error = True

    if error:
        sys.exit(ExitCodes.ERROR)
