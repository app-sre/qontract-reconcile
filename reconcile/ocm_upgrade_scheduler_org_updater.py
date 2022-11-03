import logging

from reconcile import queries
from reconcile.utils.ocm import OCMMap


QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org-updater"


def run(dry_run):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    for ocm in ocms:
        upgrade_policy_defaults = ocm.get("upgradePolicyDefaults")
        if not upgrade_policy_defaults:
            continue

        upgrade_policy_clusters = ocm.get("upgradePolicyClusters") or []
        ocm_map = OCMMap(
            ocms=[ocm],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )
        ocm_name = ocm["name"]
        ocm = ocm_map[ocm_name]

        for ocm_cluster_name in ocm.clusters:
            found = [
                c for c in upgrade_policy_clusters if c["name"] == ocm_cluster_name
            ]
            if not found:
                logging.info(["add_cluster", ocm_name, ocm_cluster_name])

        for up_cluster in upgrade_policy_clusters:
            up_cluster_name = up_cluster["name"]
            found = [c for c in ocm.clusters if c == up_cluster_name]
            if not found:
                logging.info(["delete_cluster", ocm_name, up_cluster_name])
