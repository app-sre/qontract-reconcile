from reconcile import queries
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-addons-upgrade-tests-trigger"


def run(dry_run):
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
    for ocm_info in ocms:
        addon_upgrade_tests = ocm_info.get("addonUpgradeTests")
        if not addon_upgrade_tests:
            continue

        ocm_map = OCMMap(
            ocms=[ocm_info],
            integration=QONTRACT_INTEGRATION,
            settings=settings,
            init_addons=True,
        )

        ocm = ocm_map[ocm_info["name"]]
        print(ocm_info["name"])
        for cluster in ocm.clusters:
            print(cluster)
            cluster_addons = ocm.get_cluster_addons(cluster, with_version=True)
            print(cluster_addons)
