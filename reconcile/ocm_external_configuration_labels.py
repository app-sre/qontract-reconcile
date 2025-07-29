import json
import logging
import sys
from collections.abc import Iterable, Mapping
from typing import Any

from reconcile import queries
from reconcile.status import ExitCodes
from reconcile.utils.constants import DEFAULT_THREAD_POOL_SIZE
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-external-configuration-labels"


def get_allowed_labels_for_cluster(cluster: Mapping[str, Any]) -> set[str]:
    allowed_labels = cluster.get("ocm", {}).get(
        "allowedClusterExternalConfigLabels", []
    )
    return set(allowed_labels)


def fetch_current_state(
    clusters: Iterable[Mapping[str, Any]],
) -> tuple[OCMMap, list[dict[str, Any]]]:
    settings = queries.get_app_interface_settings()
    ocm_map = OCMMap(
        clusters=clusters, integration=QONTRACT_INTEGRATION, settings=settings
    )

    current_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        allowed_labels = get_allowed_labels_for_cluster(cluster)
        ocm = ocm_map.get(cluster_name)
        labels = ocm.get_external_configuration_labels(cluster_name)
        for key, value in labels.items():
            if key not in allowed_labels:
                continue
            item = {
                "label": {"key": key, "value": value},
                "cluster": cluster_name,
            }
            current_state.append(item)

    return ocm_map, current_state


def fetch_desired_state(clusters: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    desired_state = []
    for cluster in clusters:
        cluster_name = cluster["name"]
        allowed_labels = get_allowed_labels_for_cluster(cluster)
        labels = json.loads(cluster["externalConfiguration"]["labels"])
        for key, value in labels.items():
            if key not in allowed_labels:
                raise ValueError(
                    f"Unsupported external configuration label '{key}' in cluster '{cluster_name}'"
                )
            item = {"label": {"key": key, "value": value}, "cluster": cluster_name}
            desired_state.append(item)

    return desired_state


def calculate_diff(
    current_state: Iterable[dict[str, Any]],
    desired_state: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    diffs = []
    err = False
    for d_item in desired_state:
        c_items = [c for c in current_state if d_item == c]
        if not c_items:
            d_item["action"] = "create"
            diffs.append(d_item)

    for c_item in current_state:
        d_items = [d for d in desired_state if c_item == d]
        if not d_items:
            c_item["action"] = "delete"
            diffs.append(c_item)

    return diffs, err


def sort_diffs(diff: Mapping[str, Any]) -> int:
    """Sort diffs so we delete first and create later"""
    if diff["action"] == "delete":
        return 1
    return 2


def act(dry_run: bool, diffs: list[dict[str, Any]], ocm_map: OCMMap) -> None:
    diffs.sort(key=sort_diffs)
    for diff in diffs:
        action = diff["action"]
        cluster = diff["cluster"]
        label = diff["label"]
        logging.info([action, cluster, label])
        if not dry_run:
            ocm = ocm_map.get(cluster)
            if action == "create":
                ocm.create_external_configuration_label(cluster, label)
            elif action == "delete":
                ocm.delete_external_configuration_label(cluster, label)


def _cluster_is_compatible(cluster: Mapping[str, Any]) -> bool:
    return (
        cluster.get("ocm") is not None
        and cluster.get("externalConfiguration") is not None
    )


def run(
    dry_run: bool,
    gitlab_project_id: str | None = None,
    thread_pool_size: int = DEFAULT_THREAD_POOL_SIZE,
) -> None:
    clusters = queries.get_clusters()
    clusters = [
        c
        for c in clusters
        if integration_is_enabled(QONTRACT_INTEGRATION, c) and _cluster_is_compatible(c)
    ]

    if not clusters:
        logging.debug(
            "No external configuration labels definitions found in app-interface"
        )
        sys.exit(ExitCodes.SUCCESS)

    ocm_map, current_state = fetch_current_state(clusters)
    desired_state = fetch_desired_state(clusters)
    diffs, err = calculate_diff(current_state, desired_state)
    act(dry_run, diffs, ocm_map)

    if err:
        sys.exit(ExitCodes.ERROR)
