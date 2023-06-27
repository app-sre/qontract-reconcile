from collections import defaultdict
from typing import Optional

from reconcile import queries
from reconcile.aus import base as aus
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.metrics import AUSClusterVersionRemainingSoakDaysGauge
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    ConfiguredUpgradePolicy,
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
    OCMMap,
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
        settings = queries.get_app_interface_settings()
        cluster_like_objects = [
            policy.dict(by_alias=True) for policy in org_upgrade_spec.specs
        ]

        ocm_map = OCMMap(
            clusters=cluster_like_objects,
            integration=self.name,
            settings=settings,
            init_version_gates=True,
        )
        ocm_org = ocm_map[org_upgrade_spec.org.name]
        current_state = aus.fetch_current_state(
            clusters=org_upgrade_spec.specs, ocm_map=ocm_map
        )
        upgrade_policies = aus.fetch_upgrade_policies(
            clusters=org_upgrade_spec.specs, ocm_map=ocm_map
        )
        version_data_map = aus.get_version_data_map(
            dry_run=dry_run,
            upgrade_policies=upgrade_policies,
            ocm_map=ocm_map,
            integration=self.name,
        )

        self.expose_remaining_soak_day_metrics(
            ocm_env=org_upgrade_spec.org.environment.name,
            upgrade_policies=upgrade_policies,
            version_data=version_data_map.get(ocm_org.ocm_env, ocm_org.org_id),
            available_upgrades=ocm_org.non_blocked_cluster_upgrades,
        )

        diffs = aus.calculate_diff(
            current_state, upgrade_policies, ocm_map, version_data_map
        )
        aus.act(dry_run, diffs, ocm_map)

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        specs_per_org: dict[str, list[ClusterUpgradeSpec]] = defaultdict(list)
        for cluster in (
            aus_clusters_query(query_func=gql.get_api().query).clusters or []
        ):
            supported_product = (
                cluster.spec and cluster.spec.product in SUPPORTED_OCM_PRODUCTS
            )
            in_env_shard = cluster.ocm and ocm_env.name == cluster.ocm.environment.name
            in_org_shard = org_ids is None or (
                cluster.ocm and cluster.ocm.org_id in org_ids
            )
            in_shard = in_env_shard and in_org_shard
            cluster_uuid = cluster.spec.external_id if cluster.spec else None
            if (
                integration_is_enabled(self.name, cluster)  # pylint: disable=R0916
                and cluster.ocm
                and cluster.upgrade_policy
                and supported_product
                and cluster_uuid
                and in_shard
            ):
                specs_per_org[cluster.ocm.name].append(
                    ClusterUpgradeSpec(
                        name=cluster.name,
                        cluster_uuid=cluster_uuid,
                        ocm=cluster.ocm,
                        upgradePolicy=cluster.upgrade_policy,
                        current_version=cluster.spec.version if cluster.spec else "?",
                    )
                )
        return {
            org_name: OrganizationUpgradeSpec(org=specs[0].ocm, specs=specs)
            for org_name, specs in specs_per_org.items()
        }

    def expose_remaining_soak_day_metrics(
        self,
        ocm_env: str,
        upgrade_policies: list[ConfiguredUpgradePolicy],
        version_data: VersionData,
        available_upgrades: dict[str, list[str]],
    ) -> None:
        for up in upgrade_policies:
            upgrades = available_upgrades.get(up.cluster) or []
            if not upgrades:
                continue

            workload_soaking_upgrades = [
                aus.soaking_days(version_data, upgrades, wl, False)
                for wl in up.workloads
            ]
            for version in upgrades or []:
                soaks = [s.get(version, 0) for s in workload_soaking_upgrades]
                metrics.set_gauge(
                    AUSClusterVersionRemainingSoakDaysGauge(
                        integration=self.name,
                        ocm_env=ocm_env,
                        cluster_uuid=up.cluster_uuid,
                        soaking_version=version,
                    ),
                    max(up.conditions.soakDays - (min(soaks) or 0), 0),
                )
