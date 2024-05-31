from collections.abc import Iterable
from typing import Any

import reconcile.openshift_resources_base as orb
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-prometheus-rules"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 0, 0)
PROVIDERS = ["prometheus-rule"]


def run(
    dry_run: bool,
    thread_pool_size: int = 10,
    internal: bool | None = None,
    use_jump_host: bool = True,
    cluster_name: Iterable[str] | None = None,
    exclude_cluster: Iterable[str] | None = None,
    namespace_name: str | None = None,
) -> None:
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    orb.run(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        use_jump_host=use_jump_host,
        providers=PROVIDERS,
        cluster_name=cluster_name,
        exclude_cluster=exclude_cluster,
        namespace_name=namespace_name,
        init_api_resources=True,
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    return orb.early_exit_desired_state(PROVIDERS)


def desired_state_shard_config() -> DesiredStateShardConfig:
    return orb.desired_state_shard_config()
