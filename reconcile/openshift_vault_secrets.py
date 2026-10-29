from __future__ import annotations

import logging
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from deepdiff import DeepHash

import reconcile.openshift_resources_base as orb
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.runtime.integration import DesiredStateShardConfig
from reconcile.utils.semver_helper import make_semver

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from reconcile.openshift_base import ClusterMap

QONTRACT_INTEGRATION = "openshift-vault-secrets"
QONTRACT_INTEGRATION_VERSION = make_semver(1, 9, 3)
PROVIDERS = ["vault-secret"]


class SecretInUseDeletionGate:
    """Prevent openshift-vault-secrets from deleting Secrets used by live Pods."""

    def __init__(self, oc_map: ClusterMap) -> None:
        self._oc_map = oc_map

    def is_delete_allowed(
        self,
        *,
        cluster: str,
        namespace: str,
        resource_type: str,
        resource_name: str,
    ) -> bool:
        if resource_type != "Secret":
            return True

        oc = self._oc_map.get_cluster(cluster)
        consumers: list[Mapping[str, Any]] = [
            pod
            for pod in oc.get_items("Pod", namespace=namespace)
            if oc.is_resource_used_in_pod(resource_name, "Secret", pod)
        ]
        if not consumers:
            return True

        consumer_names = ", ".join(
            f"Pod/{pod['metadata']['name']}" for pod in consumers
        )
        logging.error(
            "[%s/%s] Deletion blocked: Secret %s is referenced by %s. "
            "Remove the reference, complete the workload rollout, wait for old "
            "Pods to terminate, and retry.",
            cluster,
            namespace,
            resource_name,
            consumer_names,
        )
        return False


def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    cluster_name: str | None = None,
    namespace_name: str | None = None,
    defer: Callable | None = None,
) -> None:
    orb.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    orb.QONTRACT_INTEGRATION_VERSION = QONTRACT_INTEGRATION_VERSION

    orb.run(
        dry_run=dry_run,
        thread_pool_size=thread_pool_size,
        internal=internal,
        providers=PROVIDERS,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
        deletion_gate_factory=SecretInUseDeletionGate,
    )


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
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
