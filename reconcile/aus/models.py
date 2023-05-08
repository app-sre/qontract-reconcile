from __future__ import annotations

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
    """This class is used to represent the conditions of upgrade policies."""

    mutexes: Optional[list[str]]
    soakDays: Optional[int]
    sector: Optional[Sector]

    def get_mutexes(self) -> list[str]:
        return self.mutexes or []


class ConfiguredUpgradePolicy(BaseModel):
    """This class is used to represent the configuration for upgrade policies.
    It is a reflection of the configuration done in GraphQL.
    It is more specific than the generated dataclasses, as it supports
    additional attributes.
    """

    cluster: str
    conditions: ConfiguredUpgradePolicyConditions
    current_version: str
    schedule: str
    workloads: list[str]


class ConfiguredAddonUpgradePolicy(ConfiguredUpgradePolicy):
    """A class to represent the configuration for addon upgrade policies.
    See also description of baseclass ConfiguredUpgradePolicy."""

    addon_id: str

    @classmethod
    def from_cluster_upgrade_spec(
        cls,
        ous: ClusterUpgradeSpec,
        current_version: str,
        addon_id: str,
        sector: Optional[Sector] = None,
    ) -> ConfiguredAddonUpgradePolicy:
        created_instance = cls(
            cluster=ous.name,
            conditions=ConfiguredUpgradePolicyConditions(
                mutexes=ous.upgrade_policy.conditions.mutexes,
                soakDays=ous.upgrade_policy.conditions.soak_days,
            ),
            schedule=ous.upgrade_policy.schedule,
            workloads=ous.upgrade_policy.workloads,
            current_version=current_version,
            addon_id=addon_id,
        )
        if sector:
            created_instance.conditions.sector = sector

        return created_instance


class ConfiguredClusterUpgradePolicy(ConfiguredUpgradePolicy):
    """A class to represent the configuration for cluster upgrade policies.
    See also description of baseclass ConfiguredUpgradePolicy."""

    available_upgrades: Optional[list[str]]
    channel: str

    @classmethod
    def from_cluster_upgrade_spec(
        cls,
        ous: ClusterUpgradeSpec,
        current_version: str,
        channel: str,
        available_upgrades: Optional[list[str]] = None,
        sector: Optional[Sector] = None,
    ) -> ConfiguredClusterUpgradePolicy:
        created_instance = cls(
            cluster=ous.name,
            conditions=ConfiguredUpgradePolicyConditions(
                mutexes=ous.upgrade_policy.conditions.mutexes,
                soakDays=ous.upgrade_policy.conditions.soak_days,
            ),
            schedule=ous.upgrade_policy.schedule,
            workloads=ous.upgrade_policy.workloads,
            current_version=current_version,
            channel=channel,
            available_upgrades=available_upgrades,
        )
        if sector:
            created_instance.conditions.sector = sector

        return created_instance
