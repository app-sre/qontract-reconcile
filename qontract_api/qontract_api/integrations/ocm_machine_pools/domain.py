"""Pydantic domain models for OCM machine pool reconciliation.

Desired-state models ported from the legacy reconcile/ocm_machine_pools.py
integration: what app-interface wants each cluster's machine pools (OSD / ROSA
classic) or node pools (ROSA HCP) to look like. Wire-format models for what
OCM actually has live in qontract_utils.ocm_api.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, model_validator
from qontract_utils.ocm_api import OcmNodePoolAws, OcmTaint


class ClusterType(StrEnum):
    """The OCM cluster product, deciding the pool shape it reconciles with."""

    OSD = "osd"
    ROSA_CLASSIC = "rosa"
    ROSA_HCP = "hypershift"


class DesiredMachinePoolAutoscaling(BaseModel, frozen=True):
    """Machine pool autoscaling (OSD / ROSA classic) - plural field names."""

    min_replicas: int
    max_replicas: int

    @model_validator(mode="after")
    def validate_scaling(self) -> Self:
        """Reject min > max, on the coerced values (legacy parity: equal is OK)."""
        if self.min_replicas > self.max_replicas:
            raise ValueError(
                "max_replicas must be greater than or equal to min_replicas"
            )
        return self


class DesiredNodePoolAutoscaling(BaseModel, frozen=True):
    """Node pool autoscaling (ROSA HCP) - singular field names."""

    min_replica: int
    max_replica: int

    @model_validator(mode="after")
    def validate_scaling(self) -> Self:
        """Reject min > max, on the coerced values (legacy parity: equal is OK)."""
        if self.min_replica > self.max_replica:
            raise ValueError("max_replica must be greater than or equal to min_replica")
        return self


class DesiredMachinePool(BaseModel, frozen=True):
    """A desired machine pool on an OSD or ROSA classic cluster."""

    id: str
    instance_type: str
    replicas: int | None = None
    autoscaling: DesiredMachinePoolAutoscaling | None = None
    labels: dict[str, str] | None = None
    taints: list[OcmTaint] | None = None

    @model_validator(mode="after")
    def validate_scaling(self) -> Self:
        """Reject autoscaling together with a fixed replica count.

        Presence-based (`is not None`) so replicas=0 with autoscaling is
        rejected too.
        """
        if self.autoscaling is not None and self.replicas is not None:
            raise ValueError("autoscaling and replicas are mutually exclusive")
        return self


class DesiredNodePool(BaseModel, frozen=True):
    """A desired node pool on a ROSA HCP (HyperShift) cluster."""

    id: str
    aws_node_pool: OcmNodePoolAws
    subnet: str | None = None
    replicas: int | None = None
    autoscaling: DesiredNodePoolAutoscaling | None = None
    labels: dict[str, str] | None = None
    taints: list[OcmTaint] | None = None

    @model_validator(mode="after")
    def validate_scaling(self) -> Self:
        """Reject autoscaling together with a fixed replica count.

        Presence-based (`is not None`) so replicas=0 with autoscaling is
        rejected too.
        """
        if self.autoscaling is not None and self.replicas is not None:
            raise ValueError("autoscaling and replicas are mutually exclusive")
        return self


DesiredPool = DesiredMachinePool | DesiredNodePool


class DesiredClusterMachinePools(BaseModel, frozen=True):
    """A cluster with its desired pools, sent by the client.

    The pool shape must match the cluster type: ROSA HCP clusters reconcile
    node pools, everything else machine pools.
    """

    name: str = Field(..., description="Cluster name")
    cluster_id: str = Field(..., description="OCM cluster ID")
    cluster_type: ClusterType
    pools: list[DesiredPool] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_pool_shape(self) -> Self:
        """Reject pool shapes that don't match the cluster type."""

        def _pool_kind(pool: DesiredPool) -> str:
            return "node pool" if isinstance(pool, DesiredNodePool) else "machine pool"

        expected = (
            "node pool"
            if self.cluster_type == ClusterType.ROSA_HCP
            else ("machine pool")
        )
        for pool in self.pools:
            kind = _pool_kind(pool)
            if kind != expected:
                raise ValueError(
                    f"cluster {self.name} is of type {self.cluster_type.value} "
                    f"({expected}s) but declares a {kind}: {pool.id}"
                )
        return self


__all__ = [
    "ClusterType",
    "DesiredClusterMachinePools",
    "DesiredMachinePool",
    "DesiredMachinePoolAutoscaling",
    "DesiredNodePool",
    "DesiredNodePoolAutoscaling",
    "DesiredPool",
]
