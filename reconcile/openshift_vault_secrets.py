from collections import defaultdict
from typing import Any

from deepdiff import DeepHash

import reconcile.openshift_resources_base as orb
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-vault-secrets"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 3)
PROVIDERS = ["vault-secret"]


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
    namespaces, _ = orb.get_namespaces(PROVIDERS)

    state_for_clusters = defaultdict(list)
    for ns in namespaces:
        state_for_clusters[ns["cluster"]["name"]].append(ns)

    return {
        "state": {
            cluster: {"shard": cluster, "hash": DeepHash(state).get(state)}
            for cluster, state in state_for_clusters.items()
        }
    }


def desired_state_shard_config() -> DesiredStateShardConfig:
    return DesiredStateShardConfig(
        shard_arg_name="cluster_name",
        shard_path_selectors={
            "state.*.shard",
        },
        sharded_run_review=lambda proposal: len(proposal.proposed_shards) <= 2,
    )
