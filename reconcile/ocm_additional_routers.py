import sys
import logging
import json

from reconcile import queries

from reconcile.status import ExitCodes
from reconcile.utils.ocm import OCM_PRODUCT_OSD, OCMMap

QONTRACT_INTEGRATION = "ocm-additional-routers"

SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


def fetch_current_state(clusters):
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )

    current_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        ocm = ocm_map.get(cluster_name)
        routers = ocm.get_additional_routers(cluster_name)
        for router in routers:
            router["cluster"] = cluster_name
            current_state.append(router)

    return ocm_map, current_state


def fetch_desired_state(clusters):
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        for router in cluster["additionalRouters"]:
            listening = "internal" if router["private"] else "external"
            item = {"listening": listening, "cluster": cluster_name}
            selectors = router.get("route_selectors", None)
            if selectors:
                item["route_selectors"] = json.loads(selectors)
            desired_state.append(item)

    return desired_state


def calculate_diff(current_state, desired_state):
    diffs = []
    for d in desired_state:
        c = [c for c in current_state if d.items() <= c.items()]
        if not c:
            d["action"] = "create"
            diffs.append(d)

    for c in current_state:
        d = [d for d in desired_state if d.items() <= c.items()]
        if not d:
            c["action"] = "delete"
            diffs.append(c)

    return diffs


def sort_diffs(diff):
    """Sort diffs so we delete first and create later"""
    if diff["action"] == "delete":
        return 1
    else:
        return 2


def act(dry_run, diffs, ocm_map):
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        action = diff.pop("action")
        cluster = diff.pop("cluster")
        logging.info([action, cluster])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if action == "create":
                ocm.create_additional_router(cluster, diff)
            elif action == "delete":
                ocm.delete_additional_router(cluster, diff)


def run(dry_run):
    clusters = queries.get_clusters()
    clusters = [
        c
        for c in clusters
        if c.get("additionalRouters") is not None
        and c["spec"]["product"] in SUPPORTED_OCM_PRODUCTS
    ]
    if not clusters:
        logging.debug("No additionalRouters definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)
