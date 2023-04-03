from collections import defaultdict
from typing import Optional

from reconcile import queries
from reconcile.aus import base as aus
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_clusters import (
    query as aus_clusters_query,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import gql
from reconcile.utils.disabled_integrations import integration_is_enabled
from reconcile.utils.ocm import (
    OCM_PRODUCT_OSD,
    OCMMap,
)

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler"
SUPPORTED_OCM_PRODUCTS = [OCM_PRODUCT_OSD]


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
        current_state = aus.fetch_current_state(
            clusters=cluster_like_objects, ocm_map=ocm_map
        )
        desired_state = aus.fetch_desired_state(
            clusters=cluster_like_objects, ocm_map=ocm_map
        )
        version_data_map = aus.get_version_data_map(
            dry_run=dry_run,
            upgrade_policies=desired_state,
            ocm_map=ocm_map,
            integration=self.name,
        )
        diffs = aus.calculate_diff(
            current_state, desired_state, ocm_map, version_data_map
        )
        aus.act(dry_run, diffs, ocm_map)

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        specs_per_org: dict[str, list[ClusterUpgradeSpec]] = defaultdict(list)
        for cluster in (
            aus_clusters_query(query_func=gql.get_api().query).clusters or []
        ):
            supported_product = (
                cluster.spec and cluster.spec.product in SUPPORTED_OCM_PRODUCTS
            )
            in_env_shard = cluster.ocm and ocm_env.name == cluster.ocm.environment.name
            in_org_shard = org_name is None or (
                cluster.ocm and cluster.ocm.name == org_name
            )
            in_shard = in_env_shard and in_org_shard
            if (
                integration_is_enabled(self.name, cluster)
                and cluster.ocm
                and cluster.upgrade_policy
                and supported_product
                and in_shard
            ):
                specs_per_org[cluster.ocm.name].append(
                    ClusterUpgradeSpec(
                        name=cluster.name,
                        ocm=cluster.ocm,
                        upgradePolicy=cluster.upgrade_policy,
                    )
                )
        return {
            org_name: OrganizationUpgradeSpec(org=specs[0].ocm, specs=specs)
            for org_name, specs in specs_per_org.items()
        }
