import json
import logging

import reconcile.utils.mr.ocm_upgrade_scheduler_org_updates as ousou

from reconcile import mr_client_gateway
from reconcile import queries
from reconcile.utils.ocm import OCMMap


QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org-updater"


def run(dry_run, gitlab_project_id):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    for ocm_info in ocms:
        updates = []
        create_update_mr = False
        upgrade_policy_defaults = ocm_info.get("upgradePolicyDefaults")
        if not upgrade_policy_defaults:
            continue

        upgrade_policy_clusters = ocm_info.get("upgradePolicyClusters") or []
        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )
        ocm_name = ocm_info["name"]
        ocm_path = ocm_info["path"]
        ocm = ocm_map[ocm_name]

        for ocm_cluster_name in ocm.clusters:
            found = [
                c for c in upgrade_policy_clusters if c["name"] == ocm_cluster_name
            ]
            if not found:
                ocm_cluster_labels = ocm.get_external_configuration_labels(
                    ocm_cluster_name
                )
                for default in upgrade_policy_defaults:
                    default_name = default["name"]
                    match_labels: dict[str, str] = json.loads(default["matchLabels"])
                    if match_labels.items() <= ocm_cluster_labels.items():
                        create_update_mr = True
                        logging.info(
                            ["add_cluster", ocm_name, ocm_cluster_name, default_name]
                        )
                        item = {
                            "action": "add",
                            "cluster": ocm_cluster_name,
                            "policy": default["upgradePolicy"],
                        }
                        updates.append(item)
                        break

        for up_cluster in upgrade_policy_clusters:
            up_cluster_name = up_cluster["name"]
            found = [c for c in ocm.clusters if c == up_cluster_name]
            if not found:
                create_update_mr = True
                logging.info(["delete_cluster", ocm_name, up_cluster_name])
                item = {
                    "action": "delete",
                    "cluster": up_cluster_name,
                }
                updates.append(item)

        if create_update_mr and not dry_run:
            mr_cli = mr_client_gateway.init(gitlab_project_id=gitlab_project_id)
            updates_info = {
                "path": "data" + ocm_path,
                "name": ocm_name,
                "updates": updates,
            }
            mr = ousou.CreateOCMUpgradeSchedulerOrgUpdates(updates_info)
            mr.submit(cli=mr_cli)
