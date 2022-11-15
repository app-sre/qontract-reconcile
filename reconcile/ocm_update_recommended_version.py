import functools
import semver
from reconcile import queries, mr_client_gateway
from reconcile.utils.mr.ocm_update_recommended_version import (
    CreateOCMUpdateRecommendedVersion,
    UpdateInfo,
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


def run(dry_run: bool, gitlab_project_id: int):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()

    for ocm_info in ocms:
        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )

        rv_current = ocm_info.get("recommendedVersion")
        rv_weight = ocm_info.get("recommendedVersionWeight")
        high_weight = 1
        majority_weight = 1

        if rv_weight:
            if rv_weight["highest"] is not None:
                high_weight = rv_weight["highest"]
            if rv_weight["majority"] is not None:
                majority_weight = rv_weight["majority"]

        if rv_current:
            current, pending = ocm_map.cluster_specs()

            if len(current) == 0:
                continue

            versions = [current[k].spec.version for k in current]
            rv_new = recommended_version(versions, high_weight, majority_weight)
            if semver.compare(rv_new, rv_current) == 1:
                update = UpdateInfo(
                    path=f"data{ocm_info['path']}",
                    name=ocm_info["name"],
                    recommended_version=rv_new,
                )
                mr = CreateOCMUpdateRecommendedVersion(update)
                if not dry_run:
                    mr_cli = mr_client_gateway.init(
                        gitlab_project_id=gitlab_project_id, sqs_or_gitlab="gitlab"
                    )
                    mr.submit(cli=mr_cli)
