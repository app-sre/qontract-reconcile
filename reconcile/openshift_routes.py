from typing import Any

import reconcile.openshift_resources_base as orb

from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-routes"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 3)
PROVIDERS = ["route"]


def run(
    dry_run,
    thread_pool_size=10,
    internal=None,
    use_jump_host=True,
    cluster_name=None,
    namespace_name=None,
    defer=None,
):
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    orb.run(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        providers=PROVIDERS,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
    )


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    return orb.early_exit_desired_state(PROVIDERS)
