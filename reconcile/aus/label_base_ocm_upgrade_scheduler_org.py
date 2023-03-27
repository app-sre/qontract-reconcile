from typing import Optional

from reconcile.aus.models import OrganizationUpgradeSpec
from reconcile.aus.ocm_upgrade_scheduler_org import (
    OCMClusterUpgradeSchedulerOrgIntegration,
)


class LabelBasedOCMClusterUpgradeSchedulerOrgIntegration(
    OCMClusterUpgradeSchedulerOrgIntegration
):
    def get_organization_upgrade_spec(
        self, org_name: Optional[str] = None
    ) -> dict[str, OrganizationUpgradeSpec]:
        return {
            # todo
            # discover orgs + clusters via labels
            # and create OrganizationUpgradeSpec objects
            # from them
        }
