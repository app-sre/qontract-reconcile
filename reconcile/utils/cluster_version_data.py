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

from reconcile.utils.state import State


class WorkloadHistory(BaseModel):
    soak_days: float = 0.0
    reporting: list[str] = Field(default_factory=list)


class VersionHistory(BaseModel):
    workloads: dict[str, WorkloadHistory] = Field(default_factory=dict)


class VersionData(BaseModel):
    check_in: Optional[datetime]
    versions: dict[str, VersionHistory] = Field(default_factory=dict)

    def jsondict(self) -> dict[str, Any]:
        return json.loads(self.json())

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

    def aggregate(self, added: "VersionData", added_org_name: str) -> None:
        known_workloads = self.workloads()
        for version, version_data in added.versions.items():
            for workload, workload_data in version_data.workloads.items():
                # skip if our current version data does not contain this remote workload
                if workload not in known_workloads:
                    continue
                w = self.workload_history(version, workload, WorkloadHistory())
                w.soak_days += workload_data.soak_days
                ocm_clusters = [
                    f"{added_org_name}/{cluster}" for cluster in workload_data.reporting
                ]
                w.reporting += ocm_clusters


def get_version_data(state: State, ocm_name: str) -> VersionData:
    vd = state.get(ocm_name, {})
    return VersionData(**vd)
