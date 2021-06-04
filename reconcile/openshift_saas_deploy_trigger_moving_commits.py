import sys
import logging

import reconcile.queries as queries
import reconcile.openshift_saas_deploy_trigger_base as osdt_base
import reconcile.utils.threaded as threaded

from reconcile.status import ExitCodes
from reconcile.utils.defer import defer
from reconcile.utils.semver_helper import make_semver
from reconcile.utils.sharding import is_in_shard


QONTRACT_INTEGRATION = 'openshift-saas-deploy-trigger-moving-commits'
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


@defer
def run(dry_run, thread_pool_size=10, internal=None,
        use_jump_host=True, defer=None):
    saas_files = queries.get_saas_files(v1=True, v2=True)
    if not saas_files:
        logging.error('no saas files found')
        sys.exit(ExitCodes.ERROR)
    saas_files = [sf for sf in saas_files if is_in_shard(sf['name'])]

    # Remove saas-file targets that are disabled
    for saas_file in saas_files[:]:
        resource_templates = saas_file['resourceTemplates']
        for rt in resource_templates[:]:
            targets = rt['targets']
            for target in targets[:]:
                if target['disable']:
                    targets.remove(target)

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

    trigger_specs = saasherder.get_moving_commits_diff(dry_run)
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
            state_update_method=saasherder.update_moving_commit,
            integration=QONTRACT_INTEGRATION,
            integration_version=QONTRACT_INTEGRATION_VERSION
        )
    error = True in trigger_errors

    if error:
        sys.exit(ExitCodes.ERROR)
