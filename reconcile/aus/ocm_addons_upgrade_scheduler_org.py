import functools

from pydantic import BaseModel

from reconcile.aus import base as aus
from reconcile.aus.base import (
    AbstractUpgradePolicy,
    AddonUpgradePolicy,
    init_addon_service,
)
from reconcile.aus.cluster_version_data import VersionData
from reconcile.aus.healthchecks import (
    AUSClusterHealthCheckProvider,
    build_cluster_health_providers_for_organization,
)
from reconcile.aus.metrics import (
    AUSAddonUpgradePolicyInfoMetric,
    AUSAddonVersionRemainingSoakDaysGauge,
)
from reconcile.aus.models import (
    ClusterAddonUpgradeSpec,
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import metrics
from reconcile.utils.ocm.addons import (
    OCMAddonInstallation,
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
        with init_ocm_base_client_for_org(
            org_upgrade_spec.org, self.secret_reader
        ) as org_ocm_api:
            current_state = aus.fetch_current_state(
                org_ocm_api,
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
                ).get(
                    org_upgrade_spec.org.environment.name, org_upgrade_spec.org.org_id
                )

                addon_current_state: list[AddonUpgradePolicy] = [
                    s
                    for s in current_state
                    if isinstance(s, AddonUpgradePolicy) and s.addon_id == addon_id
                ]

                self.expose_remaining_soak_day_metrics(
                    org_upgrade_spec=org_upgrade_spec,
                    version_data=version_data,
                    current_state=addon_current_state,
                    metrics_builder=functools.partial(
                        AUSAddonVersionRemainingSoakDaysGauge,
                        integration=self.name,
                        ocm_env=org_upgrade_spec.org.environment.name,
                        addon=addon_id,
                    ),
                )

                diffs = calculate_diff(
                    addon_current_state=addon_current_state,
                    org_upgrade_spec=addon_org_upgrade_spec,
                    ocm_api=org_ocm_api,
                    version_data=version_data,
                    addon_id=addon_id,
                )
                aus.act(
                    dry_run,
                    diffs,
                    org_ocm_api,
                    addon_id=addon_id,
                )

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment
    ) -> dict[str, OrganizationUpgradeSpec]:
        """
        Build the upgrade specs for all relevant organizations. Each org spec contains
        one spec per cluster and addon.
        """
        organizations = self.get_orgs_for_environment(
            ocm_env, only_addon_managed_upgrades=True
        )
        if not organizations:
            return {}

        addon_service = init_addon_service(ocm_env)

        # lookup cluster in OCM to figure out if they exist
        # and to get their UUID
        with init_ocm_base_client(ocm_env, self.secret_reader) as ocm_api:
            clusters = discover_clusters_for_organizations(
                ocm_api, [org.org_id for org in organizations]
            )
            addon_latest_versions = addon_service.get_addon_latest_versions(ocm_api)
            addons_per_cluster: dict[str, list[OCMAddonInstallation]] = {
                cluster.ocm_cluster.name: addon_service.get_addons_for_cluster(
                    ocm_api=ocm_api,
                    cluster_id=cluster.ocm_cluster.id,
                    addon_latest_versions=addon_latest_versions,
                    required_state="ready",
                )
                for cluster in clusters
            }

        cluster_health_providers = self._health_check_providers_for_env(ocm_env.name)

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
                    cluster_health_provider=build_cluster_health_providers_for_organization(
                        org=o,
                        providers=cluster_health_providers,
                    ),
                ),
            )
            for o in organizations
        }

    def _build_addon_upgrade_spec(
        self,
        org: AUSOCMOrganization,
        clusters_by_name: dict[str, OCMCluster],
        addons_per_cluster: dict[str, list[OCMAddonInstallation]],
        cluster_health_provider: AUSClusterHealthCheckProvider,
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
                health=cluster_health_provider.cluster_health(
                    cluster_external_id=clusters_by_name[cluster.name].external_id,
                    org_id=org.org_id,
                ),
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
        for cluster_upgrade_spec in org_upgrade_spec.specs:
            if not isinstance(cluster_upgrade_spec, ClusterAddonUpgradeSpec):
                continue
            mutexes = cluster_upgrade_spec.upgrade_policy.conditions.mutexes
            metrics.set_info(
                AUSAddonUpgradePolicyInfoMetric(
                    integration=self.name,
                    ocm_env=ocm_env,
                    cluster_uuid=cluster_upgrade_spec.cluster_uuid,
                    org_id=cluster_upgrade_spec.org.org_id,
                    org_name=org_upgrade_spec.org.name,
                    channel=cluster_upgrade_spec.cluster.version.channel_group,
                    current_version=cluster_upgrade_spec.current_version,
                    cluster_name=cluster_upgrade_spec.name,
                    schedule=cluster_upgrade_spec.upgrade_policy.schedule,
                    sector=cluster_upgrade_spec.upgrade_policy.conditions.sector or "",
                    mutexes=",".join(mutexes) if mutexes else "",
                    soak_days=str(
                        cluster_upgrade_spec.upgrade_policy.conditions.soak_days or 0
                    ),
                    workloads=",".join(cluster_upgrade_spec.upgrade_policy.workloads),
                    addon=cluster_upgrade_spec.addon.id,
                    product=cluster_upgrade_spec.cluster.product.id,
                    hypershift=cluster_upgrade_spec.cluster.hypershift.enabled,
                ),
            )


def calculate_diff(
    addon_current_state: list[AddonUpgradePolicy],
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
        if addon_id == current.addon_id and (
            current.schedule_type == "automatic" or current.state == "completed"
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
                        addon_service=init_addon_service(
                            org_upgrade_spec.org.environment
                        ),
                    ),
                )
            )
    return diffs
