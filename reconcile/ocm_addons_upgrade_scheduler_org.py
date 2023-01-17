import dataclasses
from typing import Any

import reconcile.ocm_upgrade_scheduler as ous
from reconcile import queries
from reconcile.utils.cluster_version_data import VersionData
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-addons-upgrade-scheduler-org"


def calculate_diff(
    addon_current_state: list[dict[str, Any]],
    addon_desired_state: list[dict[str, Any]],
    ocm_map: OCMMap,
    version_data_map: dict[str, VersionData],
    addon_id: str = "",
) -> list[dict[str, str]]:
    diffs = ous.calculate_diff(
        addon_current_state,
        addon_desired_state,
        ocm_map,
        version_data_map,
        addon_id=addon_id,
    )
    for c in addon_current_state:
        if addon_id == c["addon_id"] and c["schedule_type"] == "automatic":
            diffs.append(
                {
                    "action": "delete",
                    "cluster": c["cluster"],
                    "version": c["schedule_type"],
                    "id": c["id"],
                }
            )
    return diffs


@dataclasses.dataclass(unsafe_hash=True)
class ResultKey:
    ocm_map: OCMMap
    ocm_name: str
    addon_id: str


@dataclasses.dataclass
class Result:
    current_state: list[dict[str, Any]]
    desired_state: list[dict[str, Any]]
    diffs: list[dict[str, str]]


def compute(
    settings: dict, ocms: list[dict[str, Any]], dry_run: bool
) -> dict[ResultKey, Result]:
    ocms = [o for o in ocms if o.get("addonManagedUpgrades")]
    results: dict[ResultKey, Result] = {}
    for ocm in ocms:
        upgrade_policy_clusters = ocm.get("upgradePolicyClusters")
        if not upgrade_policy_clusters:
            continue

        # patch cluster items with ocm instance
        for c in upgrade_policy_clusters:
            c["ocm"] = ocm
        ocm_map = OCMMap(
            clusters=upgrade_policy_clusters,
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
            init_addons=True,
        )

        current_state = ous.fetch_current_state(
            upgrade_policy_clusters, ocm_map, addons=True
        )
        desired_state = ous.fetch_desired_state(
            upgrade_policy_clusters, ocm_map, addons=True
        )
        addon_ids = set(a["addon_id"] for a in desired_state)
        for addon_id in addon_ids:
            addon_current_state = [
                c for c in current_state if c["addon_id"] == addon_id
            ]
            addon_desired_state = [
                d for d in desired_state if d["addon_id"] == addon_id
            ]
            version_data_map = ous.get_version_data_map(
                dry_run, addon_desired_state, ocm_map, addon_id=addon_id
            )
            diffs = ous.calculate_diff(
                addon_current_state,
                addon_desired_state,
                ocm_map,
                version_data_map,
                addon_id=addon_id,
            )
            for c in addon_current_state:
                if addon_id == c["addon_id"] and c["schedule_type"] == "automatic":
                    diffs.append(
                        {
                            "action": "delete",
                            "cluster": c["cluster"],
                            "version": c["schedule_type"],
                            "id": c["id"],
                        }
                    )
            results[ResultKey(ocm_map, ocm["name"], addon_id)] = Result(
                current_state=addon_current_state,
                desired_state=addon_desired_state,
                diffs=diffs,
            )
    return results


def run(dry_run: bool) -> None:
    # patch integration name for state usage
    ous.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    results = compute(settings, ocms, dry_run)

    for key, res in results.items():
        ous.act(dry_run, res.diffs, key.ocm_map, addon_id=key.addon_id)
