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


def get_updated_recommended_versions(
    ocm_info: dict[str, Any], cluster: dict[str, OCMSpec]
) -> list[dict[str, str]]:

    recommended_versions = ocm_info.get("recommendedVersions") or []

    high_weight, majority_weight = get_version_weights(ocm_info)

    rv_updated: list[dict[str, str]] = []
    for workload in ocm_info["upgradePolicyAllowedWorkloads"] or []:
        cluster_workload = [
            c["name"]
            for c in ocm_info.get("upgradePolicyClusters") or []
            if workload in c["upgradePolicy"]["workloads"]
        ]
        versions = [cluster[k].spec.version for k in cluster if k in cluster_workload]

        rv_workload = [rv for rv in recommended_versions if rv["workload"] == workload]
        if len(rv_workload) > 1:
            raise ValueError("Expecting zero or one recommended Version per workload!")
        elif len(rv_workload) == 0:
            # Workload was not configured, thus create a new rv for it
            rv_current = {"workload": workload}
        else:
            # Workload exists
            rv_current = rv_workload[0]

        if len(versions) > 0:
            # Managed clusters exist for this workload
            rv_current["recommendedVersion"] = recommended_version(
                versions, high_weight, majority_weight
            )
            rv_updated.append(rv_current)
        elif len(rv_workload) == 1 and len(versions) == 0:
            # No clusters exist, but a rv was added, probably a manual setting
            rv_updated.append(rv_workload[0])
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
