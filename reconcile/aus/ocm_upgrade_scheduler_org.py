from typing import Optional

from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.aus.ocm_upgrade_scheduler import OCMClusterUpgradeSchedulerIntegration
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.utils import gql
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
        self, ocm_env: OCMEnvironment, org_ids: Optional[set[str]]
    ) -> dict[str, OrganizationUpgradeSpec]:
        # query all OCM organizations from app-interface and filter by and orgs
        organizations = [
            org
            for org in aus_organizations_query(
                query_func=gql.get_api().query
            ).organizations
            or []
            if org.environment.name == ocm_env.name
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

        return {
            org.name: OrganizationUpgradeSpec(
                org=org,
                specs=self._build_cluster_upgrade_specs(
                    org,
                    {
                        c.ocm_cluster.name: c.ocm_cluster
                        for c in clusters
                        if c.organization_id == org.org_id
                    },
                ),
            )
            for org in organizations
        }

    def _build_cluster_upgrade_specs(
        self, org: AUSOCMOrganization, clusters_by_name: dict[str, OCMCluster]
    ) -> list[ClusterUpgradeSpec]:
        return [
            ClusterUpgradeSpec(
                org=org,
                upgradePolicy=cluster.upgrade_policy,
                cluster=clusters_by_name[cluster.name],
            )
            for cluster in org.upgrade_policy_clusters or []
            # clusters that are not in the UUID dict will be ignored because
            # they don't exist in the OCM organization (or have been deprovisioned)
            if cluster.name in clusters_by_name
        ]
