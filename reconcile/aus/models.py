from __future__ import annotations

from typing import Optional

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
)

from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicy
from reconcile.utils.ocm import Sector


class ClusterUpgradeSpec(BaseModel):
    """
    An upgrade spec for a cluster.
    """

    name: str
    ocm: AUSOCMOrganization
    upgrade_policy: ClusterUpgradePolicy = Field(..., alias="upgradePolicy")
    cluster_uuid: str
    current_version: str


class ClusterValidationError(BaseModel):
    """
    A validation error for a cluster.
    """

    cluster_uuid: str
    messages: list[str]


class OrganizationUpgradeSpec(BaseModel):
    """
    Represents all cluster upgrade specs for an OCM organization.
    """

    org: AUSOCMOrganization
    specs: list[ClusterUpgradeSpec] = Field(default_factory=list)
    _cluster_errors: dict[str, ClusterValidationError] = PrivateAttr(
        default_factory=dict
    )

    @property
    def has_validation_errors(self) -> bool:
        return self.nr_of_validation_errors > 0

    @property
    def nr_of_validation_errors(self) -> int:
        return len(self._cluster_errors)

    @property
    def cluster_errors(self) -> list[ClusterValidationError]:
        return list(self._cluster_errors.values())

    def add_cluster_error(self, cluster_uuid: str, message: str) -> None:
        if cluster_uuid not in self._cluster_errors:
            self._cluster_errors[cluster_uuid] = ClusterValidationError(
                cluster_uuid=cluster_uuid, messages=[]
            )
        self._cluster_errors[cluster_uuid].messages.append(message)


class ConfiguredUpgradePolicyConditions(BaseModel):
    """This class is used to represent the conditions of upgrade policies."""

    mutexes: Optional[list[str]]
    soakDays: int
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
    cluster_uuid: str
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
            cluster_uuid=ous.cluster_uuid,
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
            cluster_uuid=ous.cluster_uuid,
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
