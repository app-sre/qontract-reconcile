import sys
import logging

import reconcile.queries as queries
import reconcile.openshift_saas_deploy_trigger_base as osdt_base
import reconcile.utils.threaded as threaded

from reconcile.status import ExitCodes
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-upstream-jobs'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def fetch_current_state(jenkins_map):
    return {instance_name: jenkins.get_jobs_state()
            for instance_name, jenkins in jenkins_map.items()}


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    saas_files = queries.get_saas_files(v1=False, v2=True)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(ExitCodes.ERROR)
    saas_files = [sf for sf in saas_files if is_in_shard(sf['name'])]

    saasherder, jenkins_map, oc_map, settings = \
        osdt_base.setup(
            saas_files=saas_files,
            thread_pool_size=thread_pool_size,
            internal=internal,
            use_jump_host=use_jump_host,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION
        )
    defer(lambda: oc_map.cleanup())

    current_state = fetch_current_state(jenkins_map)
    trigger_specs = saasherder.get_upstream_jobs_diff(dry_run, current_state)
    # This will be populated by osdt_base.trigger in the below loop and
    # we need it to be consistent across all iterations
    already_triggered = set()

    trigger_errors = \
        threaded.run(
            osdt_base.trigger,
            trigger_specs,
            thread_pool_size,
            dry_run=dry_run,
            jenkins_map=jenkins_map,
            oc_map=oc_map,
            already_triggered=already_triggered,
            settings=settings,
            state_update_method=saasherder.update_upstream_job,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION
        )
    error = True in trigger_errors

    if error:
        sys.exit(ExitCodes.ERROR)
