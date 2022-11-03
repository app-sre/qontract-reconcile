from reconcile import queries

import reconcile.ocm_upgrade_scheduler as ous

from reconcile.utils.ocm import OCMMap


QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org-updater"


def run(dry_run):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    for ocm in ocms:
        upgrade_policy_defaults = ocm.get("upgradePolicyDefaults")
        if not upgrade_policy_defaults:
            continue

        upgrade_policy_clusters = upgrade_policy_defaults = (
            ocm.get("upgradePolicyClusters") or []
        )
        ocm_map = OCMMap(
            ocm=ocm,
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_version_gates=True,
        )
        ocm_name = ocm["name"]
        ocm = ocm_map[ocm_name]
        print(ocm.name)
