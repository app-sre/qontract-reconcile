import logging
import sys
from collections.abc import Callable, Iterable, Mapping
from typing import Any

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.helpers import flatten
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-resourcequotas"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)


def construct_resource(quota: Mapping[str, Any]) -> OR:
    body: dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "ResourceQuota",
        "metadata": {"name": quota["name"]},
        "spec": {
            "hard": flatten(quota["resources"]),
        },
    }
    if quota["scopes"]:
        body["spec"]["scopes"] = quota["scopes"]
    return OR(
        body,
        QONTRACT_INTEGRATION,
        QONTRACT_INTEGRATION_VERSION,
        error_details=quota["name"],
    )


def fetch_desired_state(
    namespaces: Iterable[Mapping[str, Any]],
    ri: ResourceInventory,
    oc_map: ob.ClusterMap,
) -> None:
    for namespace_info in namespaces:
        namespace = namespace_info["name"]
        cluster = namespace_info["cluster"]["name"]
        if not oc_map.get(cluster):
            continue
        quotas = (namespace_info.get("quota") or {}).get("quotas") or []
        for quota in quotas:
            quota_name = quota["name"]
            quota_resource = construct_resource(quota)
            ri.add_desired(
                cluster, namespace, "ResourceQuota", quota_name, quota_resource
            )


@defer
def run(
    dry_run: bool,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
    internal: bool | None = None,
    use_jump_host: bool = True,
    take_over: bool = True,
    defer: Callable | None = None,
) -> None:
    namespaces = [
        namespace_info
        for namespace_info in queries.get_namespaces()
        if namespace_info.get("quota") and not ob.is_namespace_deleted(namespace_info)
    ]

    if not namespaces:
        logging.debug("No ResourceQuota definition found in app-interface!")
        sys.exit(0)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["ResourceQuota"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)
    fetch_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size)

    if ri.has_error_registered():
        sys.exit(1)
