from dataclasses import (
    asdict,
    dataclass,
    field,
)
from typing import (
    Any,
    Optional,
)

from reconcile.utils.state import State


@dataclass
class WorkloadHistory:
    soak_days: float = 0.0
    reporting: list[str] = field(default_factory=list)


@dataclass
class VersionHistory:
    workloads: dict[str, WorkloadHistory]


@dataclass
class VersionData:
    check_in: str
    versions: dict[str, VersionHistory]

    def workload_history(
        self, version: str, workload: str, default: Optional[WorkloadHistory] = None
    ) -> WorkloadHistory:
        if not default:
            vh = self.versions.get(version, VersionHistory({}))
            return vh.workloads.get(workload, WorkloadHistory())
        vh = self.versions.setdefault(version, VersionHistory({}))
        return vh.workloads.setdefault(workload, default)

    def asdict(self) -> dict[str, Any]:
        return asdict(self)

    def save(self, state: State, ocm_name: str) -> None:
        state.add(ocm_name, asdict(self), force=True)


def version_data_from_dict(d: dict[str, Any]) -> VersionData:
    ret = VersionData(d["check_in"], {})
    for version, version_data in d.setdefault("versions", {}).items():
        for workload, workload_data in version_data["workloads"].items():
            wh = WorkloadHistory(workload_data["soak_days"], workload_data["reporting"])
            ret.workload_history(version, workload, wh)
    return ret


def get_version_data(state: State, ocm_name: str) -> VersionData:
    vd = state.get(ocm_name, {})
    return version_data_from_dict(vd)


def default_workload_history() -> WorkloadHistory:
    return WorkloadHistory()
