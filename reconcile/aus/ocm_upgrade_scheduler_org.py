from typing import Optional

from reconcile.aus.models import (
    ClusterUpgradeSpec,
    OrganizationUpgradeSpec,
)
from reconcile.aus.ocm_upgrade_scheduler import OCMClusterUpgradeSchedulerIntegration
from reconcile.gql_definitions.advanced_upgrade_service.aus_organization import (
    query as aus_organizations_query,
)
from reconcile.utils import gql

QONTRACT_INTEGRATION = "ocm-upgrade-scheduler-org"


class OCMClusterUpgradeSchedulerOrgIntegration(OCMClusterUpgradeSchedulerIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_organization_upgrade_spec(
        self, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        return organization_upgrade_spec(org_name=org_name)


def organization_upgrade_spec(
    org_name: Optional[str] = None,
) -> dict[str, OrganizationUpgradeSpec]:
    return {
        org.name: OrganizationUpgradeSpec(
            org=org,
            specs=[
                ClusterUpgradeSpec(
                    name=cluster.name,
                    ocm=org,
                    upgradePolicy=cluster.upgrade_policy,
                )
                for cluster in org.upgrade_policy_clusters or []
            ],
        )
        for org in aus_organizations_query(query_func=gql.get_api().query).organizations
        or []
        if org_name is None or org.name == org_name
    }
