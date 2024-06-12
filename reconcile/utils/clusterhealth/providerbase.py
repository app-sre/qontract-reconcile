from abc import ABC, abstractmethod

from pydantic import BaseModel


class ClusterHealth(BaseModel):
    source: str
    errors: set[str] | None = None

    def has_health_errors(self) -> bool:
        return bool(self.errors)


def build_assumed_cluster_health() -> ClusterHealth:
    return ClusterHealth(source="assumption")


class ClusterHealthProvider(ABC):
    """
    A base class for cluster health providers.
    """

    @abstractmethod
    def cluster_health(self, cluster_external_id: str, org_id: str) -> ClusterHealth:
        """
        Provides health information for an individual cluster in an organization
        """


class EmptyClusterHealthProvider(ClusterHealthProvider):
    """
    A default implementation of a cluster health provider that returns no health
    information. Not every environment has a healthprovider available and this
    implementation helps avoiding to check for the existance of a health provider
    in various code places for such environments.
    """

    def cluster_health(self, cluster_external_id: str, org_id: str) -> ClusterHealth:
        return build_assumed_cluster_health()
