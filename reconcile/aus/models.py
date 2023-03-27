from pydantic import (
    BaseModel,
    Field,
)

from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicy


class ClusterUpgradeSpec(BaseModel):
    name: str
    ocm: AUSOCMOrganization
    upgrade_policy: ClusterUpgradePolicy = Field(..., alias="upgradePolicy")


class OrganizationUpgradeSpec(BaseModel):
    org: AUSOCMOrganization
    specs: list[ClusterUpgradeSpec]
