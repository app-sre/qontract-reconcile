from collections import defaultdict
from typing import Optional

from reconcile.aus import base as aus
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.metrics import AUSClusterVersionRemainingSoakDaysGauge
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_clusters import (
    query as aus_clusters_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    OCM_PRODUCT_ROSA,
)
from reconcile.utils.ocm.clusters import discover_clusters_for_organizations
from reconcile.utils.ocm_base_client import (
    init_ocm_base_client,
    init_ocm_base_client_for_org,
)

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD, OCM_PRODUCT_ROSA]


class OCMClusterUpgradeSchedulerIntegration(
    aus.AdvancedUpgradeSchedulerBaseIntegration
):
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

        self.expose_remaining_soak_day_metrics(
            ocm_env=org_upgrade_spec.org.environment.name,
            org_upgrade_spec=org_upgrade_spec,
            version_data=version_data_map.get(
                org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
            ),
        )

        diffs = aus.calculate_diff(
            current_state, org_upgrade_spec, ocm_api, version_data
        )
        aus.act(dry_run, diffs, ocm_api)

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        specs_per_org: dict[str, list[ClusterUpgradeSpec]] = defaultdict(list)
        ai_clusters = aus_clusters_query(query_func=gql.get_api().query).clusters or []

        # read cluster details from OCM
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        cluster_details = {
            c.ocm_cluster.external_id: c.ocm_cluster
            for c in discover_clusters_for_organizations(
                ocm_api, {c.ocm.org_id for c in ai_clusters if c.ocm}
            )
        }

        for cluster in ai_clusters:
            supported_product = (
                cluster.spec and cluster.spec.product in SUPPORTED_OCM_PRODUCTS
            )
            in_env_shard = cluster.ocm and ocm_env.name == cluster.ocm.environment.name
            in_org_shard = org_ids is None or (
                cluster.ocm and cluster.ocm.org_id in org_ids
            )
            in_shard = in_env_shard and in_org_shard
            cluster_uuid = cluster.spec.external_id if cluster.spec else None
            cluster_detail = cluster_details.get(cluster_uuid) if cluster_uuid else None
            if (
                integration_is_enabled(self.name, cluster)  # pylint: disable=R0916
                and cluster.ocm
                and cluster.upgrade_policy
                and supported_product
                and cluster_detail
                and in_shard
            ):
                specs_per_org[cluster.ocm.name].append(
                    ClusterUpgradeSpec(
                        org=cluster.ocm,
                        upgradePolicy=cluster.upgrade_policy,
                        cluster=cluster_detail,
                    )
                )
        return {
            org_name: OrganizationUpgradeSpec(org=specs[0].org, specs=specs)
            for org_name, specs in specs_per_org.items()
        }

    def expose_remaining_soak_day_metrics(
        self,
        ocm_env: str,
        org_upgrade_spec: OrganizationUpgradeSpec,
        version_data: VersionData,
    ) -> None:
        for spec in org_upgrade_spec.specs:
            upgrades = spec.cluster.version.available_upgrades or []
            if not upgrades:
                continue

            workload_soaking_upgrades = [
                aus.soaking_days(version_data, upgrades, wl, False)
                for wl in spec.upgrade_policy.workloads
            ]
            for version in upgrades or []:
                soaks = [s.get(version, 0) for s in workload_soaking_upgrades]
                metrics.set_gauge(
                    AUSClusterVersionRemainingSoakDaysGauge(
                        integration=self.name,
                        ocm_env=ocm_env,
                        cluster_uuid=spec.cluster.external_id,
                        soaking_version=version,
                    ),
                    max(
                        (spec.upgrade_policy.conditions.soak_days or 0)
                        - (min(soaks) or 0),
                        0,
                    ),
                )
