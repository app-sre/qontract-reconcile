import functools
import logging
from typing import Any

import semver

from reconcile import (
    mr_client_gateway,
    queries,
)
from reconcile.ocm.types import OCMSpec
from reconcile.utils.mr.ocm_update_recommended_version import (
    CreateOCMUpdateRecommendedVersion,
)
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-update-recommended-version"


def get_highest(version_set: set[str]) -> str:
    sorted_version_set = sorted(
        version_set, key=functools.cmp_to_key(semver.compare), reverse=True
    )
    return sorted_version_set[0]


def get_majority(version_set: set[str], versions: list[str]) -> str:
    return max(version_set, key=versions.count)


def recommended_version(
    versions: list[str], high_weight: int = 0, majority_weight: int = 0
) -> str:
    version_set = set(versions)
    version_count = {k: versions.count(k) for k in version_set}

    highest = get_highest(version_set)
    majority = get_majority(version_set, versions)

    high_value = version_count[highest] * high_weight
    major_value = version_count[majority] * majority_weight

    if major_value > high_value:
        return majority

    return highest


def get_version_weights(ocm: dict[str, Any]) -> tuple[int, int]:
    rv_weight = ocm.get("recommendedVersionWeight")
    high_weight = 1
    majority_weight = 1
    if rv_weight:
        if rv_weight.get("highest") is not None:
            high_weight = rv_weight["highest"]
        if rv_weight.get("majority") is not None:
            majority_weight = rv_weight["majority"]
    return high_weight, majority_weight


def format_initial_version(version: str, channel: str) -> str:
    if channel == "stable":
        return f"openshift-v{version}"
    return f"openshift-v{version}-{channel}"


def get_updated_recommended_versions(
    ocm_info: dict[str, Any], cluster: dict[str, OCMSpec]
) -> list[dict[str, str]]:
    high_weight, majority_weight = get_version_weights(ocm_info)

    rv_updated: list[dict[str, str]] = []

    channel_workload_versions: dict[tuple[str, str], list[str]] = {}

    for uc in ocm_info["upgradePolicyClusters"] or []:
        cluster_name = uc["name"]
        if cluster_name in cluster:
            for workload in uc["upgradePolicy"]["workloads"]:
                channel_workload = (workload, cluster[cluster_name].spec.channel)
                channel_workload_versions.setdefault(channel_workload, [])
                channel_workload_versions[channel_workload].append(
                    cluster[cluster_name].spec.version
                )

    for cwv_items in channel_workload_versions.items():
        cwv, versions = cwv_items
        workload, channel = cwv
        rv = recommended_version(versions, high_weight, majority_weight)
        rv_current = {
            "workload": workload,
            "channel": channel,
            "recommendedVersion": rv,
            "initialVersion": format_initial_version(rv, channel),
        }
        rv_updated.append(rv_current)

    return rv_updated


def run(dry_run: bool, gitlab_project_id: int) -> None:
    settings = queries.get_app_interface_settings()
    ocm = queries.get_openshift_cluster_managers()

    for ocm_info in ocm:
        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )

        current, _ = ocm_map.cluster_specs()
        if len(current) == 0:
            continue

        rv_updated = get_updated_recommended_versions(ocm_info, current)

        if not rv_updated:
            continue

        if rv_updated == ocm_info["recommendedVersions"]:
            continue

        mr = CreateOCMUpdateRecommendedVersion(
            ocm_name=ocm_info["name"],
            path=f"data{ocm_info['path']}",
            recommended_versions=rv_updated,
        )
        if not dry_run:
            logging.info(f"Creating MR for {ocm_info['name']}")
            mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
            mr.submit(cli=mr_cli)
