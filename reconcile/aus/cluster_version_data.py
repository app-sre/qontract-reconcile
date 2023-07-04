import json
from datetime import datetime
from typing import (
    Any,
    Iterable,
    Optional,
)

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.aus.models import OrganizationUpgradeSpec
from reconcile.utils.semver_helper import parse_semver
from reconcile.utils.state import State


class WorkloadHistory(BaseModel):
    soak_days: float = 0.0
    reporting: list[str] = Field(default_factory=list)


class VersionHistory(BaseModel):
    workloads: dict[str, WorkloadHistory] = Field(default_factory=dict)


class Stats(BaseModel):
    """Stats is a part of VersionData. It provides basic statistics on the OCM
    organization current cluster versions. Currently only
    the minimum version, globally in the org and per workload, is being stored.
    This class also has a `inherited` field which will contain at runtime a
    computation of the same statistics for `inheritedVersionData` organizations.
    This field is only computed and set at runtime and not stored in state.
    It is used to compute version upgradeability according to cross-org
    inheritance.
    """

    min_version: str
    min_version_per_workload: dict[str, str] = Field(default_factory=dict)
    inherited: Optional["Stats"]

    def inherit(self, added: "Stats") -> None:
        """adds the provided stats to our inherited data
        If we already have inherited data, we will merge the stats data:
        compute new minimums and add missing data
        """
        if not self.inherited:
            self.inherited = added
            return
        self.inherited.min_version = min(
            self.inherited.min_version, added.min_version, key=parse_semver
        )
        for workload, added_version in added.min_version_per_workload.items():
            v = self.inherited.min_version_per_workload.get(workload, added_version)
            self.inherited.min_version_per_workload[workload] = min(
                v, added_version, key=parse_semver
            )

    def validate_against_inherited(self, version: str, workloads: list[str]) -> bool:
        """Returns True only if version is less or equal than any of the inherited version
        for these workloads.
        If one of the worloads is not part of the inherited stats, we will check against
        the global minimum version.
        If there are no inherited stats, we consider the version as valid
        """
        if not self.inherited:
            return True
        semver = parse_semver(version)
        all_workloads_found = True
        all_workload_ok = True
        # check that inherited orgs run at least that version for our workloads
        for w in workloads:
            all_workloads_found = w in self.inherited.min_version_per_workload
            if not all_workloads_found:
                break
            if semver > parse_semver(self.inherited.min_version_per_workload[w]):
                all_workload_ok = False
        if all_workloads_found and not all_workload_ok:
            return False
        if not all_workloads_found:
            # if some of our workload is not inherited, check the global min_version
            # from the other orgs
            if semver > parse_semver(self.inherited.min_version):
                return False
        return True


class VersionData(BaseModel):
    """VersionData holds information about cluster versions and their history
    for a given OCM organization. This data is stored in a State and used to
    decide if a given version can be used for an upgrade according to our
    upgrade policies.
    """

    check_in: Optional[datetime]
    versions: dict[str, VersionHistory] = Field(default_factory=dict)
    stats: Optional[Stats]

    def jsondict(self) -> dict[str, Any]:
        return json.loads(self.json(exclude_none=True))

    def save(self, state: State, ocm_name: str) -> None:
        state.add(ocm_name, self.jsondict(), force=True)

    def workload_history(
        self, version: str, workload: str, default: Optional[WorkloadHistory] = None
    ) -> WorkloadHistory:
        if not default:
            vh = self.versions.get(version, VersionHistory())
            return vh.workloads.get(workload, WorkloadHistory())
        vh = self.versions.setdefault(version, VersionHistory())
        return vh.workloads.setdefault(workload, default)

    def workloads(self) -> Iterable[str]:
        workloads: set[str] = set()
        for v in self.versions.values():
            workloads.update(v.workloads.keys())
        return workloads

    def update_stats(self, org_upgrade_spec: OrganizationUpgradeSpec) -> None:
        """Update the versiondata stats with the provided upgrade_policies info"""
        min_version_per_workload: dict[str, str] = {}
        for spec in org_upgrade_spec.specs:
            current_version = spec.current_version
            for w in spec.upgrade_policy.workloads:
                min_ver = min_version_per_workload.setdefault(w, current_version)
                if parse_semver(current_version) < parse_semver(min_ver):
                    min_version_per_workload[w] = current_version

        if min_version_per_workload:
            min_version = min(min_version_per_workload.values(), key=parse_semver)
            self.stats = Stats(
                min_version=min_version,
                min_version_per_workload=min_version_per_workload,
            )

    def aggregate(self, added: "VersionData", added_scope: str) -> None:
        """aggregate an other version data with this one.
        this adds new value and merges the ones we we already have
        """
        known_workloads = self.workloads()
        for version, version_data in added.versions.items():
            for workload, workload_data in version_data.workloads.items():
                # skip if our current version data does not contain this remote workload
                if workload not in known_workloads:
                    continue
                w = self.workload_history(version, workload, WorkloadHistory())
                w.soak_days += workload_data.soak_days
                ocm_clusters = [
                    f"{added_scope}/{cluster}" for cluster in workload_data.reporting
                ]
                w.reporting += ocm_clusters
        if self.stats and added.stats:
            self.stats.inherit(added.stats)

    def validate_against_inherited(self, version: str, workloads: list[str]) -> bool:
        if not self.stats:
            return True
        return self.stats.validate_against_inherited(version, workloads)


class VersionDataMap:
    def __init__(self) -> None:
        self._data: dict[str, VersionData] = {}

    def add(self, ocm_env: str, org_id: str, version_data: VersionData) -> None:
        self._data[f"{ocm_env}/{org_id}"] = version_data

    def get(self, ocm_env: str, org_id: str) -> VersionData:
        return self._data[f"{ocm_env}/{org_id}"]

    def items(self) -> Iterable[tuple[str, VersionData]]:
        return self._data.items()


def get_version_data(state: State, key: str) -> VersionData:
    vd = state.get(key, {})
    return VersionData(**vd)
