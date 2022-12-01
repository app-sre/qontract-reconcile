import reconcile.ocm_upgrade_scheduler as ous
from reconcile import queries
from reconcile.utils.ocm import OCMMap

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org"


def run(dry_run):
    # patch integration name for state usage
    ous.QONTRACT_INTEGRATION = QONTRACT_INTEGRATION
    settings = queries.get_app_interface_settings()
    ocms = queries.get_openshift_cluster_managers()
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
        )

        current_state = ous.fetch_current_state(upgrade_policy_clusters, ocm_map)
        desired_state = ous.fetch_desired_state(upgrade_policy_clusters, ocm_map)
        version_history = ous.get_version_data_map(dry_run, desired_state, ocm_map)
        diffs = ous.calculate_diff(
            current_state, desired_state, ocm_map, version_history
        )
        ous.act(dry_run, diffs, ocm_map)
