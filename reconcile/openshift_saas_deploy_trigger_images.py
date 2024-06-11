import sys

import reconcile.openshift_saas_deploy_trigger_base as osdt_base
from reconcile.status import ExitCodes
from reconcile.utils.saasherder import TriggerTypes
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-saas-deploy-trigger-images"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    include_trigger_trace: bool = False,
) -> None:
    error = osdt_base.run(
        dry_run=dry_run,
        trigger_type=TriggerTypes.CONTAINER_IMAGES,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        include_trigger_trace=include_trigger_trace,
    )

    if error:
        sys.exit(ExitCodes.ERROR)
