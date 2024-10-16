from abc import ABC, abstractmethod
from collections.abc import Mapping

from pydantic import BaseModel, Field, root_validator

from reconcile.gql_definitions.common.clusters import ClusterMachinePoolV1
from reconcile.ocm_machine_pools.abstract_autoscaling import AbstractAutoscaling
from reconcile.ocm_machine_pools.cluster_type import ClusterType
from reconcile.utils.ocm import OCM


class AbstractPool(ABC, BaseModel):
    # Abstract class for machine pools, to be implemented by OSD/HyperShift classes

    id: str
    replicas: int | None
    taints: list[Mapping[str, str]] | None
    labels: Mapping[str, str] | None
    cluster: str
    cluster_type: ClusterType = Field(..., exclude=True)
    autoscaling: AbstractAutoscaling | None
    subnet: str | None

    @root_validator()
    @classmethod
    def validate_scaling(cls, field_values):
        if field_values.get("autoscaling") and field_values.get("replicas"):
            raise ValueError("autoscaling and replicas are mutually exclusive")
        return field_values

    @abstractmethod
    def create(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def delete(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def update(self, ocm: OCM) -> None:
        pass

    @abstractmethod
    def has_diff(self, pool: ClusterMachinePoolV1) -> bool:
        pass

    @abstractmethod
    def invalid_diff(self, pool: ClusterMachinePoolV1) -> str | None:
        pass

    @abstractmethod
    def deletable(self) -> bool:
        pass

    def _has_diff_autoscale(self, pool):
        match (self.autoscaling, pool.autoscale):
            case (None, None):
                return False
            case (None, _) | (_, None):
                return True
            case _:
                return self.autoscaling.has_diff(pool.autoscale)
