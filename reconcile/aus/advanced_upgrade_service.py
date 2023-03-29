from typing import Optional

from reconcile.aus.models import OrganizationUpgradeSpec
from reconcile.aus.ocm_upgrade_scheduler_org import (
    OCMClusterUpgradeSchedulerOrgIntegration,
)
from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment

QONTRACT_INTEGRATION = "advanced-upgrade-scheduler"


class AdvancedUpgradeServiceIntegration(OCMClusterUpgradeSchedulerOrgIntegration):
    @property
    def name(self) -> str:
        return QONTRACT_INTEGRATION

    def get_ocm_env_upgrade_specs(
        self, ocm_env: OCMEnvironment, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        return {
            # todo
            # discover orgs + clusters via labels
            # and create OrganizationUpgradeSpec objects
            # from them
        }
