"""Pydantic domain models for OCM groups reconciliation."""

from __future__ import annotations

from pydantic import BaseModel, Field


class OcmGroupUser(BaseModel, frozen=True):
    """A single user membership in a cluster group."""

    cluster: str = Field(..., description="Cluster name")
    group: str = Field(..., description="Group name (e.g. dedicated-admins)")
    user: str = Field(..., description="Username")


class OcmGroupsCluster(BaseModel, frozen=True):
    """A cluster with its OCM cluster ID and managed groups, sent by the client."""

    name: str = Field(..., description="Cluster name")
    cluster_id: str = Field(..., description="OCM cluster ID")
    managed_groups: list[str] = Field(
        default_factory=list,
        description="Group names managed on this cluster (e.g. dedicated-admins)",
    )
