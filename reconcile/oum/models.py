from collections import defaultdict
from typing import Optional

from pydantic import (
    BaseModel,
    Field,
)

from reconcile.utils.ocm.cluster_groups import OCMClusterGroupId
from reconcile.utils.ocm.clusters import ClusterDetails


class ClusterError(BaseModel):
    """
    Represents an error that occurred while processing a cluster.
    """

    message: str


class ExternalGroupRef(BaseModel):
    """
    A reference to a group in an external identity provider.
    """

    provider: str
    group_id: str


class ClusterUserManagementConfiguration(BaseModel):
    """
    Provider neutral representation of cluster user management configuration.
    """

    cluster: ClusterDetails
    roles: dict[OCMClusterGroupId, list[ExternalGroupRef]] = defaultdict(list)
    errors: list[ClusterError] = Field(default_factory=list)


class OrganizationUserManagementConfiguration(BaseModel):
    org_id: str
    cluster_configs: list[ClusterUserManagementConfiguration] = Field(
        default_factory=list
    )


class ClusterUserManagementSpec(BaseModel):
    """
    Contains the resolved usernames for cluster roles and notifications.
    ClusterUserManagementSpec objects are derived from ClusterUserManagementConfiguration
    objects by resolving the ExternalGroupRef objects using the provider
    implementations.
    """

    cluster: ClusterDetails
    roles: dict[OCMClusterGroupId, set[str]]
    errors: list[ClusterError] = Field(default_factory=list)


class ClusterRoleReconcileResult(BaseModel):
    """
    Holds the result of a cluster role reconciliation.
    """

    users_added: int = 0
    users_removed: int = 0
    error: Optional[Exception] = None

    class Config:
        arbitrary_types_allowed = True
