import logging
import sys

import reconcile.queries as queries
import reconcile.openshift_saas_deploy_trigger_base as osdt_base

from reconcile.status import ExitCodes
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-configs'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    saas_files = queries.get_saas_files(v1=True, v2=True)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(ExitCodes.ERROR)

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

    trigger_specs = saasherder.get_configs_diff()
    # This will be populated by osdt_base.trigger in the below loop and
    # we need it to be consistent across all iterations
    already_triggered = []

    error = False
    for job_spec in trigger_specs:
        trigger_error = osdt_base.trigger(
            dry_run=dry_run,
            spec=job_spec,
            jenkins_map=jenkins_map,
            oc_map=oc_map,
            already_triggered=already_triggered,
            settings=settings,
            state_update_method=saasherder.update_config,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION
        )
        if trigger_error:
            error = True

    if error:
        sys.exit(ExitCodes.ERROR)
