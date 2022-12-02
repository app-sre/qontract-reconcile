import logging
import sys
from collections.abc import Mapping
from operator import itemgetter
from typing import Any

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-addons"


def fetch_current_state(clusters):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters,
        integration=QONTRACT_INTEGRATION,
        settings=settings,
        init_addons=True,
    )

    current_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        addons = ocm.get_cluster_addons(cluster_name)
        if addons:
            for addon in addons:
                addon["cluster"] = cluster_name
                sort_parameters(addon)
                current_state.append(addon)

    return ocm_map, current_state


def fetch_desired_state(clusters):
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        addons = cluster["addons"]
        for addon in addons:
            addon["id"] = addon.pop("name")
            addon["cluster"] = cluster_name
            sort_parameters(addon)
            desired_state.append(addon)

    return desired_state


def sort_parameters(addon):
    addon_parameters = addon.get("parameters")
    if addon_parameters:
        addon["parameters"] = sorted(addon_parameters, key=itemgetter("id"))


def calculate_diff(current_state, desired_state):
    diffs = []
    for d in desired_state:
        c = [c for c in current_state if d.items() <= c.items()]
        if not c:
            d["action"] = "install"
            diffs.append(d)

    return diffs


def act(dry_run, diffs, ocm_map):
    err = False
    for diff in diffs:
        action = diff.pop("action")
        cluster = diff.pop("cluster")
        addon_id = diff["id"]
        logging.info([action, cluster, addon_id])
        ocm = ocm_map.get(cluster)
        if not ocm.get_addon(addon_id):
            logging.error(f"Addon {addon_id} does not exist")
            err = True
            continue
        if not dry_run:
            if action == "install":
                try:
                    ocm.install_addon(cluster, diff)
                except Exception as e:
                    logging.error(f"could not install addon {addon_id}: {e}")
                    err = True
                    continue
            # uninstall is not supported

    return err


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return cluster.get("ocm") is not None and cluster.get("addons") is not None


def run(dry_run, gitlab_project_id=None, thread_pool_size=10):
    clusters = queries.get_clusters()
    clusters = [
        c
        for c in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    if not clusters:
        logging.debug("No Addon definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs = calculate_diff(current_state, desired_state)
    err = act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(ExitCodes.ERROR)
