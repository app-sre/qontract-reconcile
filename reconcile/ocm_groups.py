import itertools
import logging
import sys
from collections.abc import (
    Iterable,
    Mapping,
)
from typing import Any

from sretoolbox.utils import threaded

from reconcile import (
    openshift_groups,
    queries,
)
from reconcile.status import ExitCodes
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import OCMMap
from reconcile.utils.ocm.base import OCMClusterGroupId

QONTRACT_INTEGRATION = "ocm-groups"


def create_groups_list(clusters: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
    groups_list: list[dict[str, str]] = []
    for cluster_info in clusters:
        cluster = cluster_info["name"]
        groups = cluster_info["managedGroups"] or []
        groups_list.extend(
            {"cluster": cluster, "group_name": group_name} for group_name in groups
        )
    return groups_list


def get_cluster_state(
    group_items: Mapping[str, str], ocm_map: OCMMap
) -> list[dict[str, str]]:
    cluster = group_items["cluster"]
    ocm = ocm_map.get(cluster)
    group_name = group_items["group_name"]
    group = ocm.get_group_if_exists(cluster, group_name)
    if group is None:
        return []
    return [
        {"cluster": cluster, "group": group_name, "user": user}
        for user in group.get("users") or []
    ]


def fetch_current_state(
    clusters: Iterable[Mapping[str, Any]], thread_pool_size: int
) -> tuple[OCMMap, list[dict[str, str]]]:
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )
    groups_list = create_groups_list(clusters)
    results = threaded.run(
        get_cluster_state, groups_list, thread_pool_size, ocm_map=ocm_map
    )

    current_state = list(itertools.chain.from_iterable(results))
    return ocm_map, current_state


def act(diff: Mapping[str, Any], ocm_map: OCMMap) -> None:
    cluster = diff["cluster"]
    group = diff["group"]
    user = diff["user"]
    action = diff["action"]
    ocm = ocm_map.get(cluster)

    if action == "add_user_to_group":
        ocm.add_user_to_group(cluster, group, user)
    elif action == "del_user_from_group":
        ocm.del_user_from_group(cluster, group, user)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return cluster.get("ocm") is not None


def run(dry_run: bool, thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE) -> None:
    clusters = queries.get_clusters()
    if not clusters:
        logging.debug("No clusters found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    clusters = [
        c
        for c in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    if not clusters:
        logging.debug("No Groups definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters, thread_pool_size)
    desired_state = openshift_groups.fetch_desired_state(clusters=ocm_map.clusters())

    current_state = [
        s for s in current_state if s["group"] in OCMClusterGroupId.values()
    ]
    desired_state = [
        s for s in desired_state if s["group"] in OCMClusterGroupId.values()
    ]

    diffs = openshift_groups.calculate_diff(current_state, desired_state)
    openshift_groups.validate_diffs(diffs)

    for diff in diffs:
        # we do not need to create/delete groups in OCM
        if diff["action"] in {"create_group", "delete_group"}:
            continue
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, ocm_map)


def early_exit_desired_state(*args: Any, **kwargs: Any) -> dict[str, Any]:
    clusters = [
        c["name"]
        for c in queries.get_clusters() or []
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    desired_state = openshift_groups.fetch_desired_state(clusters=clusters)
    desired_state = [
        s for s in desired_state if s["group"] in OCMClusterGroupId.values()
    ]

    return {
        "state": desired_state,
    }
