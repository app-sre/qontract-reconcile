from typing import Optional

from pydantic import BaseModel

from reconcile.aus import base as aus
from reconcile.aus.base import (
    AbstractUpgradePolicy,
    AddonUpgradePolicy,
)
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.metrics import AUSOrganizationReconcileCounter
from reconcile.aus.models import (
    ClusterAddonUpgradeSpec,
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import (
    gql,
    metrics,
)
from reconcile.utils.ocm.addons import (
    OCMAddonInstallation,
    get_addon_latest_versions,
    get_addons_for_cluster,
)
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    discover_clusters_for_organizations,
)
from reconcile.utils.ocm_base_client import (
    OCMBaseClient,
    init_ocm_base_client,
    init_ocm_base_client_for_org,
)

QONTRACT_INTEGRATION = "ocm-addons-upgrade-scheduler-org"


class AUSOrgAddonUpgradeState(BaseModel):
    addon_id: str
    current_state: list[AbstractUpgradePolicy]
    upgrade_policies: list[ClusterUpgradeSpec]


class OCMAddonsUpgradeSchedulerOrgIntegration(
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
            ocm_api,
            org_upgrade_spec,
            addons=True,
        )

        addons = {
            spec.addon.id
            for spec in org_upgrade_spec.specs
            if isinstance(spec, ClusterAddonUpgradeSpec)
        }
        for addon_id in addons:
            addon_org_upgrade_spec = OrganizationUpgradeSpec(
                org=org_upgrade_spec.org,
                specs=[
                    spec
                    for spec in org_upgrade_spec.specs
                    if isinstance(spec, ClusterAddonUpgradeSpec)
                    and spec.addon.id == addon_id
                ],
            )
            version_data = aus.get_version_data_map(
                dry_run=dry_run,
                org_upgrade_spec=addon_org_upgrade_spec,
                addon_id=addon_id,
                integration=self.name,
            ).get(org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id)

            diffs = calculate_diff(
                addon_current_state=[
                    s
                    for s in current_state
                    if isinstance(s, AddonUpgradePolicy) and s.addon_id == addon_id
                ],
                org_upgrade_spec=addon_org_upgrade_spec,
                ocm_api=ocm_api,
                version_data=version_data,
                addon_id=addon_id,
            )
            aus.act(
                dry_run,
                diffs,
                ocm_api,
                addon_id=addon_id,
            )

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        """
        Build the upgrade specs for all relevant organizations. Each org spec contains
        one spec per cluster and addon.
        """
        # query all OCM organizations from app-interface and filter by and orgs
        organizations = [
            org
            for org in aus_organizations_query(
                query_func=gql.get_api().query
            ).organizations
            or []
            if org.environment.name == ocm_env.name
            and org.addon_managed_upgrades
            and (org_ids is None or org.org_id in org_ids)
        ]
        if not organizations:
            return {}

        # lookup cluster in OCM to figure out if they exist
        # and to get their UUID
        ocm_api = init_ocm_base_client(ocm_env, self.secret_reader)
        clusters = discover_clusters_for_organizations(
            ocm_api, [org.org_id for org in organizations]
        )
        addon_latest_versions = get_addon_latest_versions(ocm_api)
        addons_per_cluster: dict[str, list[OCMAddonInstallation]] = {
            cluster.ocm_cluster.name: get_addons_for_cluster(
                ocm_api=ocm_api,
                cluster_id=cluster.ocm_cluster.id,
                addon_latest_versions=addon_latest_versions,
                required_state="ready",
            )
            for cluster in clusters
        }

        return {
            o.name: OrganizationUpgradeSpec(
                org=o,
                specs=self._build_addon_upgrade_spec(
                    org=o,
                    clusters_by_name={
                        c.ocm_cluster.name: c.ocm_cluster
                        for c in clusters
                        if c.organization_id == o.org_id
                    },
                    addons_per_cluster=addons_per_cluster,
                ),
            )
            for o in organizations
        }

    def _build_addon_upgrade_spec(
        self,
        org: AUSOCMOrganization,
        clusters_by_name: dict[str, OCMCluster],
        addons_per_cluster: dict[str, list[OCMAddonInstallation]],
    ) -> list[ClusterAddonUpgradeSpec]:
        """
        builds a upgrade spec objects for each addon on each cluster
        """
        return [
            ClusterAddonUpgradeSpec(
                org=org,
                upgradePolicy=cluster.upgrade_policy,
                cluster=clusters_by_name[cluster.name],
                addon=addon,
            )
            for cluster in org.upgrade_policy_clusters or []
            if cluster.name in clusters_by_name
            # clusters that are not in the dict will be ignored because
            # they don't exist in the OCM organization (or have been deprovisioned)
            for addon in addons_per_cluster.get(cluster.name, [])
        ]

    def expose_org_upgrade_spec_metrics(
        self, ocm_env: str, org_upgrade_spec: OrganizationUpgradeSpec
    ) -> None:
        metrics.inc_counter(
            AUSOrganizationReconcileCounter(
                integration=self.name,
                ocm_env=ocm_env,
                org_id=org_upgrade_spec.org.org_id,
            )
        )


def calculate_diff(
    addon_current_state: list[AbstractUpgradePolicy],
    org_upgrade_spec: OrganizationUpgradeSpec,
    ocm_api: OCMBaseClient,
    version_data: VersionData,
    addon_id: str = "",
) -> list[aus.UpgradePolicyHandler]:
    diffs = aus.calculate_diff(
        addon_current_state,
        org_upgrade_spec,
        ocm_api,
        version_data,
        addon_id,
    )
    for current in addon_current_state:
        if (
            isinstance(current, AddonUpgradePolicy)
            and addon_id == current.addon_id
            and current.schedule_type == "automatic"
        ):
            diffs.append(
                aus.UpgradePolicyHandler(
                    action="delete",
                    policy=aus.AddonUpgradePolicy(
                        cluster=current.cluster,
                        version=current.schedule_type,
                        id=current.id,
                        addon_id=current.addon_id,
                        schedule_type=current.schedule_type,
                    ),
                )
            )
    return diffs
