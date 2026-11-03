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


def _validate_max_greater_min(
    field_values: dict[str, object], min_field: str, max_field: str
) -> None:
    """Reject autoscaling configs whose max is not greater than their min."""
    min_value = field_values.get(min_field)
    max_value = field_values.get(max_field)
    if min_value is None or max_value is None:
        raise ValueError(f"{min_field} and {max_field} must be set")
    if min_value > max_value:  # type: ignore[operator]
        raise ValueError(f"{max_field} must be greater than {min_field}")


class DesiredMachinePoolAutoscaling(BaseModel, frozen=True):
    """Machine pool autoscaling (OSD / ROSA classic) - plural field names."""

    min_replicas: int
    max_replicas: int

    @model_validator(mode="before")
    @classmethod
    def validate_scaling(cls, field_values: dict[str, object]) -> dict[str, object]:
        """Reject max <= min."""
        _validate_max_greater_min(field_values, "min_replicas", "max_replicas")
        return field_values


class DesiredNodePoolAutoscaling(BaseModel, frozen=True):
    """Node pool autoscaling (ROSA HCP) - singular field names."""

    min_replica: int
    max_replica: int

    @model_validator(mode="before")
    @classmethod
    def validate_scaling(cls, field_values: dict[str, object]) -> dict[str, object]:
        """Reject max <= min."""
        _validate_max_greater_min(field_values, "min_replica", "max_replica")
        return field_values


def _validate_autoscaling_xor_replicas(
    field_values: dict[str, object],
) -> None:
    """Reject pools declaring both autoscaling and a fixed replica count."""
    if field_values.get("autoscaling") and field_values.get("replicas"):
        raise ValueError("autoscaling and replicas are mutually exclusive")


class DesiredMachinePool(BaseModel, frozen=True):
    """A desired machine pool on an OSD or ROSA classic cluster."""

    id: str
    instance_type: str
    replicas: int | None = None
    autoscaling: DesiredMachinePoolAutoscaling | None = None
    labels: dict[str, str] | None = None
    taints: list[OcmTaint] | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_scaling(cls, field_values: dict[str, object]) -> dict[str, object]:
        """Reject autoscaling together with a fixed replica count."""
        _validate_autoscaling_xor_replicas(field_values)
        return field_values


class DesiredNodePool(BaseModel, frozen=True):
    """A desired node pool on a ROSA HCP (HyperShift) cluster."""

    id: str
    aws_node_pool: OcmNodePoolAws
    subnet: str | None = None
    replicas: int | None = None
    autoscaling: DesiredNodePoolAutoscaling | None = None
    labels: dict[str, str] | None = None
    taints: list[OcmTaint] | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_scaling(cls, field_values: dict[str, object]) -> dict[str, object]:
        """Reject autoscaling together with a fixed replica count."""
        _validate_autoscaling_xor_replicas(field_values)
        return field_values


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
