from __future__ import annotations

import logging
import re
from collections.abc import (
    Iterable,
    Mapping,
    Sequence,
)

from pydantic import (
    BaseModel,
    Field,
    PrivateAttr,
)

from reconcile.aus.healthchecks import AUSClusterHealth
from reconcile.gql_definitions.fragments.aus_organization import AUSOCMOrganization
from reconcile.gql_definitions.fragments.upgrade_policy import ClusterUpgradePolicyV1
from reconcile.utils.ocm.addons import OCMAddonInstallation
from reconcile.utils.ocm.clusters import OCMCluster
from reconcile.utils.semver_helper import parse_semver


class NodePoolSpec(BaseModel):
    id: str
    version: str


class ClusterUpgradeSpec(BaseModel):
    """
    An upgrade spec for a cluster.
    """

    org: AUSOCMOrganization
    cluster: OCMCluster
    upgrade_policy: ClusterUpgradePolicyV1 = Field(..., alias="upgradePolicy")
    health: AUSClusterHealth
    node_pools: list[NodePoolSpec] = Field(default_factory=list, alias="nodePools")

    @property
    def name(self) -> str:
        return self.cluster.name

    @property
    def cluster_uuid(self) -> str:
        return self.cluster.external_id

    @property
    def current_version(self) -> str:
        return self.cluster.version.raw_id

    @property
    def oldest_current_version(self) -> str:
        """
        Consider versions in node pools and the cluster itself, find the oldest one.
        """
        versions = [np.version for np in self.node_pools] + [self.current_version]
        return min(versions, key=parse_semver)

    @property
    def blocked_versions(self) -> set[str]:
        return set(self.org.blocked_versions or []) | set(
            self.upgrade_policy.conditions.blocked_versions or []
        )

    def version_blocked(self, version: str) -> bool:
        return any(re.search(b, version) for b in self.blocked_versions)

    def get_available_upgrades(self) -> list[str]:
        return self.cluster.available_upgrades()

    @property
    def effective_mutexes(self) -> set[str]:
        mutexes = set(self.upgrade_policy.conditions.mutexes or [])
        mutexes.add(self.cluster.id)
        return mutexes


# TODO: Addon not is-a Cluster, extract a common base to inherit
class ClusterAddonUpgradeSpec(ClusterUpgradeSpec):
    addon: OCMAddonInstallation

    def version_blocked(self, version: str) -> bool:
        addon_id = self.addon.id
        v = f"{addon_id}/{version}"
        return any(
            re.search(b, v)
            for b in self.blocked_versions
            if b.startswith(f"{addon_id}/") or b.startswith(f"^{addon_id}/")
        )

    def get_available_upgrades(self) -> list[str]:
        return self.addon.addon_version.available_upgrades

    @property
    def current_version(self) -> str:
        return self.addon.addon_version.id


class ClusterValidationError(BaseModel):
    """
    A validation error for a cluster.
    """

    cluster_uuid: str
    messages: list[str]


class OrganizationValidationError(BaseModel):
    """
    A validation error for a cluster.
    """

    message: str


class OrganizationUpgradeSpec(BaseModel):
    """
    Represents all cluster upgrade specs for an OCM organization.
    """

    org: AUSOCMOrganization
    _specs: list[ClusterUpgradeSpec] = PrivateAttr(default_factory=list)
    _cluster_errors: dict[str, ClusterValidationError] = PrivateAttr(
        default_factory=dict
    )
    _org_errors: list[OrganizationValidationError] = PrivateAttr(default_factory=list)
    _sectors: dict[str, Sector] = PrivateAttr(default_factory=dict)

    def __init__(
        self,
        org: AUSOCMOrganization,
        specs: Iterable[ClusterUpgradeSpec] | None = None,
    ) -> None:
        super().__init__(org=org)

        # extract sectors
        self._sectors = {
            s.name: Sector(
                org_id=self.org.org_id,
                name=s.name,
                max_parallel_upgrades=s.max_parallel_upgrades,
            )
            for s in self.org.sectors or []
        }

        # link sector dependencies
        for s in self.org.sectors or []:
            self._sectors[s.name].dependencies = [
                self._sectors[d.name] for d in s.dependencies or []
            ]

        # validate sectors
        for sector in self._sectors.values():
            sector.validate_dependencies()

        # register specs
        if specs:
            for spec in specs:
                self.add_spec(spec)

    @property
    def sectors(self) -> Mapping[str, Sector]:
        return self._sectors

    def add_spec(self, spec: ClusterUpgradeSpec) -> None:
        # add clusters to their sectors
        if spec.upgrade_policy.conditions.sector:
            if spec.upgrade_policy.conditions.sector not in self._sectors:
                self.add_organization_error(
                    f"sector {spec.upgrade_policy.conditions.sector} not found in organization"
                )
                self.add_cluster_error(
                    spec.cluster_uuid,
                    f"cluster {spec.cluster_uuid} references unknown sector {spec.upgrade_policy.conditions.sector}",
                )
                return
            self._sectors[spec.upgrade_policy.conditions.sector].add_spec(spec)
        self._specs.append(spec)
        self._specs.sort(key=upgrade_spec_sort_key)

    @property
    def specs(self) -> Sequence[ClusterUpgradeSpec]:
        return self._specs

    @property
    def has_validation_errors(self) -> bool:
        return self.nr_of_validation_errors > 0

    @property
    def nr_of_validation_errors(self) -> int:
        return len(self._cluster_errors) + len(self._org_errors)

    @property
    def cluster_errors(self) -> list[ClusterValidationError]:
        return list(self._cluster_errors.values())

    @property
    def organization_errors(self) -> list[OrganizationValidationError]:
        return list(self._org_errors)

    def add_cluster_error(self, cluster_uuid: str, message: str) -> None:
        if cluster_uuid not in self._cluster_errors:
            self._cluster_errors[cluster_uuid] = ClusterValidationError(
                cluster_uuid=cluster_uuid, messages=[]
            )
        self._cluster_errors[cluster_uuid].messages.append(message)

    def add_organization_error(self, message: str) -> None:
        self._org_errors.append(OrganizationValidationError(message=message))


def upgrade_spec_sort_key(spec: ClusterUpgradeSpec) -> tuple:
    """
    consider first lower versions and lower soakdays (when versions are equal)
    """
    return (
        parse_semver(spec.current_version),
        spec.upgrade_policy.conditions.soak_days or 0,
    )


class SectorConfigError(Exception):
    pass


class Sector(BaseModel):
    name: str
    max_parallel_upgrades: str | None
    dependencies: list[Sector] = Field(default_factory=list)
    _specs: dict[str, ClusterUpgradeSpec] = PrivateAttr(default_factory=dict)

    def __key(self) -> str:
        return self.name

    def __hash__(self) -> int:
        return hash(self.__key())

    def __str__(self) -> str:
        return self.name

    def add_spec(self, spec: ClusterUpgradeSpec) -> None:
        self._specs[spec.name] = spec

    @property
    def specs(self) -> Sequence[ClusterUpgradeSpec]:
        return list(self._specs.values())

    def set_specs(self, specs: Sequence[ClusterUpgradeSpec]) -> None:
        self._specs = {spec.name: spec for spec in specs}

    def _iter_dependencies(self) -> Iterable[Sector]:
        """
        iterate recursively over all the sector dependencies
        """
        logging.debug(f"[{self}] checking dependencies")
        for dep in self.dependencies or []:
            if self.name == dep.name:
                raise SectorConfigError(
                    f"[{self}] infinite sector dependency loop detected: depending on itself"
                )
            yield dep
            for d in dep._iter_dependencies():
                if self.name == d.name:
                    raise SectorConfigError(
                        f"[{self}] infinite sector dependency loop detected under {dep} dependencies"
                    )
                yield d

    def validate_dependencies(self) -> bool:
        list(self._iter_dependencies())
        return True
