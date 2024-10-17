from abc import abstractmethod

from pydantic import BaseModel

from reconcile.gql_definitions.common.clusters import ClusterSpecAutoScaleV1


class AbstractAutoscaling(BaseModel):
    def has_diff(self, autoscale: ClusterSpecAutoScaleV1) -> bool:
        return (
            self.get_min() != autoscale.min_replicas
            or self.get_max() != autoscale.max_replicas
        )

    @abstractmethod
    def get_min(self) -> int:
        pass

    @abstractmethod
    def get_max(self) -> int:
        pass
