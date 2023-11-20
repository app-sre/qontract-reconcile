import functools
from abc import ABC

from reconcile.aus import base as aus
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.metrics import (
    AUSClusterVersionRemainingSoakDaysGauge,
    AUSOrganizationVersionDataGauge,
)
from reconcile.aus.models import OrganizationUpgradeSpec
from reconcile.utils import metrics
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    OCM_PRODUCT_ROSA,
)
from reconcile.utils.ocm_base_client import init_ocm_base_client_for_org

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD, OCM_PRODUCT_ROSA]


class OCMClusterUpgradeSchedulerIntegration(
    aus.AdvancedUpgradeSchedulerBaseIntegration, ABC
):
    """
    This flavor of upgrade scheduler has been made abstract to indicate that it
    should not be used directly anymore until its code is removed.
    """

    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def process_upgrade_policies_in_org(
        self, dry_run: bool, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        ocm_api = init_ocm_base_client_for_org(org_upgrade_spec.org, self.secret_reader)
        current_state = aus.fetch_current_state(
            ocm_api=ocm_api,
            org_upgrade_spec=org_upgrade_spec,
        )
        version_data_map = aus.get_version_data_map(
            dry_run=dry_run,
            org_upgrade_spec=org_upgrade_spec,
            integration=self.name,
        )
        version_data = version_data_map.get(
            org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
        )

        self.expose_version_data_metrics(
            ocm_env=org_upgrade_spec.org.environment.name,
            org_id=org_upgrade_spec.org.org_id,
            version_data=version_data,
        )
        self.expose_remaining_soak_day_metrics(
            org_upgrade_spec=org_upgrade_spec,
            version_data=version_data,
            current_state=current_state,
            metrics_builder=functools.partial(
                AUSClusterVersionRemainingSoakDaysGauge,
                integration=self.name,
                ocm_env=org_upgrade_spec.org.environment.name,
            ),
        )

        diffs = aus.calculate_diff(
            current_state, org_upgrade_spec, ocm_api, version_data
        )
        aus.act(dry_run, diffs, ocm_api)

    def expose_version_data_metrics(
        self,
        ocm_env: str,
        org_id: str,
        version_data: VersionData,
    ) -> None:
        for version, version_history in version_data.versions.items():
            for workload, workload_history in version_history.workloads.items():
                metrics.set_gauge(
                    AUSOrganizationVersionDataGauge(
                        integration=self.name,
                        ocm_env=ocm_env,
                        org_id=org_id,
                        version=version,
                        workload=workload,
                    ),
                    workload_history.soak_days,
                )
