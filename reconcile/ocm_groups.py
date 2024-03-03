import itertools
import logging
import sys
from collections.abc import Mapping
from typing import Any

from sretoolbox.utils import threaded

from reconcile import (
    openshift_groups,
    queries,
)
from reconcile.status import ExitCodes
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-groups"


def get_cluster_state(group_items, ocm_map):
    results = []
    cluster = group_items["cluster"]
    ocm = ocm_map.get(cluster)
    group_name = group_items["group_name"]
    group = ocm.get_group_if_exists(cluster, group_name)
    if group is None:
        return results
    for user in group["users"] or []:
        results.append({"cluster": cluster, "group": group_name, "user": user})
    return results


def fetch_current_state(clusters, thread_pool_size):
    current_state = []
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )
    groups_list = openshift_groups.create_groups_list(clusters, oc_map=ocm_map)
    results = threaded.run(
        get_cluster_state, groups_list, thread_pool_size, ocm_map=ocm_map
    )

    current_state = list(itertools.chain.from_iterable(results))
    return ocm_map, current_state


def act(diff, ocm_map):
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


def run(dry_run, thread_pool_size=10):
    clusters = queries.get_clusters()
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

    # we only manage dedicated-admins via OCM
    current_state = [s for s in current_state if s["group"] == "dedicated-admins"]
    desired_state = [s for s in desired_state if s["group"] == "dedicated-admins"]

    diffs = openshift_groups.calculate_diff(current_state, desired_state)
    openshift_groups.validate_diffs(diffs)

    for diff in diffs:
        # we do not need to create/delete groups in OCM
        if diff["action"] in {"create_group", "delete_group"}:
            continue
        logging.info(list(diff.values()))

        if not dry_run:
            act(diff, ocm_map)


def early_exit_desired_state(*args, **kwargs) -> dict[str, Any]:
    clusters = [
        c["name"]
        for c in queries.get_clusters()
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    desired_state = openshift_groups.fetch_desired_state(clusters=clusters)
    # we only manage dedicated-admins via OCM
    desired_state = [s for s in desired_state if s["group"] == "dedicated-admins"]

    return {
        "state": desired_state,
    }
