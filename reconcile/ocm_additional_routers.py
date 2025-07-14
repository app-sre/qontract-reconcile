import json
import logging
import sys
from collections.abc import Iterable, Mapping, MutableMapping
from typing import Any

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    OCMMap,
)

QONTRACT_INTEGRATION = "ocm-additional-routers"

SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


def fetch_current_state(
    clusters: list[Mapping[str, Any]],
) -> tuple[OCMMap, list[dict[str, Any]]]:
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


def fetch_desired_state(clusters: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        for router in cluster["additionalRouters"]:
            listening = "internal" if router["private"] else "external"
            item: dict[str, Any] = {"listening": listening, "cluster": cluster_name}
            selectors = router.get("route_selectors", None)
            if selectors:
                item["route_selectors"] = json.loads(selectors)
            desired_state.append(item)

    return desired_state


def calculate_diff(
    current_state: Iterable[MutableMapping[str, Any]],
    desired_state: Iterable[MutableMapping[str, Any]],
) -> list[MutableMapping[str, Any]]:
    diffs = []
    for d_item in desired_state:
        c_items = [c for c in current_state if d_item.items() <= c.items()]
        if not c_items:
            d_item["action"] = "create"
            diffs.append(d_item)

    for c_item in current_state:
        d_items = [d for d in desired_state if d.items() <= c_item.items()]
        if not d_items:
            c_item["action"] = "delete"
            diffs.append(c_item)

    return diffs


def sort_diffs(diff: Mapping[str, Any]) -> int:
    """Sort diffs so we delete first and create later"""
    if diff["action"] == "delete":
        return 1
    return 2


def act(dry_run: bool, diffs: list[MutableMapping[str, Any]], ocm_map: OCMMap) -> None:
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        action = diff.pop("action")
        cluster = diff.pop("cluster")
        logging.info([action, cluster])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if ocm is None:
                logging.error(f"OCM client for cluster {cluster} not found.")
                continue
            if action == "create":
                ocm.create_additional_router(cluster, diff)
            elif action == "delete":
                ocm.delete_additional_router(cluster, diff)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return (
        cluster.get("ocm") is not None
        and cluster["spec"]["product"] in SUPPORTED_OCM_PRODUCTS
        and cluster.get("additionalRouters") is not None
    )


def run(dry_run: bool) -> None:
    clusters = [
        c
        for c in queries.get_clusters()
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]
    if not clusters:
        logging.debug("No additionalRouters definitions found in app-interface")
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)
