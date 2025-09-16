import logging
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from typing import Any

import reconcile.openshift_base as ob
from reconcile import queries
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.defer import defer
from reconcile.utils.oc import OC_Map
from reconcile.utils.openshift_resource import OpenshiftResource as OR
from reconcile.utils.openshift_resource import ResourceInventory
from reconcile.utils.semver_helper import make_semver

QONTRACT_INTEGRATION = "openshift-limitranges"
QONTRACT_INTEGRATION_VERSION = make_semver(0, 1, 0)

SUPPORTED_LIMITRANGE_TYPES = (
    "default",
    "defaultRequest",
    "max",
    "maxLimitRequestRatio",
    "min",
    "type",
)


def construct_resources(
    namespaces: Sequence[MutableMapping[str, Any]],
) -> Sequence[MutableMapping[str, Any]]:
    for namespace in namespaces:
        if "limitRanges" not in namespace:
            logging.warning(
                "limitRanges key not found on namespace %s. Skipping."
                % (namespace["name"])
            )
            continue

        # Get the linked limitRanges schema settings
        limitranges = namespace.get("limitRanges", {})

        body: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "LimitRange",
            "metadata": {
                "name": limitranges["name"],
            },
            "spec": {"limits": []},
        }

        # Build each limit item ignoring null ones
        for lr in limitranges["limits"]:
            speclimit = {}
            for ltype in SUPPORTED_LIMITRANGE_TYPES:
                if ltype in lr and lr[ltype] is not None:
                    speclimit[ltype] = lr[ltype]
            body["spec"]["limits"].append(speclimit)

        resource = OR(body, QONTRACT_INTEGRATION, QONTRACT_INTEGRATION_VERSION)

        # k8s changes an empty array to null/None. we do this here
        # to be consistent
        if len(body["spec"]["limits"]) == 0:
            body["spec"]["limits"] = None

        # Create the resources and append them to the namespace
        namespace["resources"] = [resource]

    return namespaces


def add_desired_state(
    namespaces: Sequence[Mapping[str, Any]], ri: ResourceInventory, oc_map: OC_Map
) -> None:
    for namespace in namespaces:
        cluster = namespace["cluster"]["name"]
        if not oc_map.get(cluster):
            continue
        if "resources" not in namespace:
            continue
        for resource in namespace["resources"]:
            ri.add_desired(
                namespace["cluster"]["name"],
                namespace["name"],
                resource.kind,
                resource.name,
                resource,
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
    namespaces: Sequence[MutableMapping[str, Any]] = [
        namespace_info
        for namespace_info in queries.get_namespaces()
        if namespace_info.get("limitRanges")
        and not ob.is_namespace_deleted(namespace_info)
    ]

    namespaces = construct_resources(namespaces)

    if not namespaces:
        logging.debug("No LimitRanges definition found in app-interface!")
        sys.exit(0)

    ri, oc_map = ob.fetch_current_state(
        namespaces=namespaces,
        thread_pool_size=thread_pool_size,
        integration=QONTRACT_INTEGRATION,
        integration_version=QONTRACT_INTEGRATION_VERSION,
        override_managed_types=["LimitRange"],
        internal=internal,
        use_jump_host=use_jump_host,
    )
    if defer:
        defer(oc_map.cleanup)

    add_desired_state(namespaces, ri, oc_map)
    ob.publish_metrics(ri, QONTRACT_INTEGRATION)
    ob.realize_data(dry_run, oc_map, ri, thread_pool_size, take_over=take_over)

    if ri.has_error_registered():
        sys.exit(1)
