from collections import defaultdict

from reconcile.aus.healthchecks import (
    AUSClusterHealthCheckProvider,
    build_cluster_health_providers_for_organization,
)
from reconcile.aus.models import (
    ClusterUpgradeSpec,
    NodePoolSpec,
    OrganizationUpgradeSpec,
)
from reconcile.aus.node_pool_spec import get_node_pool_specs_by_org_cluster
from reconcile.aus.ocm_upgrade_scheduler import OCMClusterUpgradeSchedulerIntegration
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils.ocm.clusters import (
    OCMCluster,
    discover_clusters_for_organizations,
)
from reconcile.utils.ocm_base_client import init_ocm_base_client

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org"


class OCMClusterUpgradeSchedulerOrgIntegration(OCMClusterUpgradeSchedulerIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment
    ) -> dict[str, OrganizationUpgradeSpec]:
        organizations = self.get_orgs_for_environment(ocm_env)
        if not organizations:
            return {}

        # lookup cluster in OCM to figure out if they exist
        # and to get their UUID
        with init_ocm_base_client(ocm_env, self.secret_reader) as ocm_api:
            clusters = discover_clusters_for_organizations(
                ocm_api, [org.org_id for org in organizations]
            )

            cluster_health_providers = self._health_check_providers_for_env(
                ocm_env.name
            )

            clusters_by_org = defaultdict(list)
            for cluster in clusters:
                clusters_by_org[cluster.organization_id].append(cluster)

            node_pool_specs_by_org_cluster = get_node_pool_specs_by_org_cluster(
                ocm_api,
                clusters_by_org,
            )

            return {
                org.name: OrganizationUpgradeSpec(
                    org=org,
                    specs=self._build_cluster_upgrade_specs(
                        org=org,
                        clusters_by_name={
                            c.ocm_cluster.name: c.ocm_cluster
                            for c in clusters_by_org[org.org_id]
                        },
                        cluster_health_provider=build_cluster_health_providers_for_organization(
                            org=org,
                            providers=cluster_health_providers,
                        ),
                        node_pool_specs_by_cluster_id=node_pool_specs_by_org_cluster.get(
                            org.org_id
                        )
                        or {},
                    ),
                )
                for org in organizations
            }

    def _build_cluster_upgrade_specs(
        self,
        org: AUSOCMOrganization,
        clusters_by_name: dict[str, OCMCluster],
        cluster_health_provider: AUSClusterHealthCheckProvider,
        node_pool_specs_by_cluster_id: dict[str, list[NodePoolSpec]],
    ) -> list[ClusterUpgradeSpec]:
        return [
            ClusterUpgradeSpec(
                org=org,
                upgradePolicy=cluster.upgrade_policy,
                cluster=clusters_by_name[cluster.name],
                health=cluster_health_provider.cluster_health(
                    cluster_external_id=clusters_by_name[cluster.name].external_id,
                    org_id=org.org_id,
                ),
                nodePools=node_pool_specs_by_cluster_id.get(ocm_cluster.id) or [],
            )
            for cluster in org.upgrade_policy_clusters or []
            # clusters that are not in the UUID dict will be ignored because
            # they don't exist in the OCM organization (or have been deprovisioned)
            if (ocm_cluster := clusters_by_name.get(cluster.name))
        ]
