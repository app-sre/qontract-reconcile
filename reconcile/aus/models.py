from typing import Optional

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicy
from reconcile.utils.ocm import Sector


class ClusterUpgradeSpec(BaseModel):
    name: str
    ocm: AUSOCMOrganization
    upgrade_policy: ClusterUpgradePolicy = Field(..., alias="upgradePolicy")


class OrganizationUpgradeSpec(BaseModel):
    org: AUSOCMOrganization
    specs: list[ClusterUpgradeSpec]


class ConfiguredUpgradePolicyConditions(BaseModel):
    mutexes: Optional[list[str]]
    soakDays: Optional[int]
    sector: Optional[Sector]

    def get_mutexes(self) -> list[str]:
        return self.mutexes or []


class ConfiguredUpgradePolicy(BaseModel):
    cluster: str
    conditions: ConfiguredUpgradePolicyConditions
    current_version: str
    schedule: str
    workloads: list[str]


class ConfiguredAddonUpgradePolicy(ConfiguredUpgradePolicy):
    addon_id: str


class ConfiguredClusterUpgradePolicy(ConfiguredUpgradePolicy):
    available_upgrades: Optional[list[str]]
    channel: str
