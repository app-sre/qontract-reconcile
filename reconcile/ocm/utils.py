from collections.abc import Mapping
from typing import (
    Any,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)


class ClusterDisableIntegration(Protocol):
    integrations: Optional[list[str]]


@runtime_checkable
class Cluster(Protocol):
    @property
    def disable(self) -> Optional[ClusterDisableIntegration]:
        pass


def cluster_disabled_integrations(
    cluster: Union[Mapping[str, Any], Cluster]
) -> list[str]:
    if isinstance(cluster, Cluster):
        if cluster.disable:
            return cluster.disable.integrations or []
    else:
        disable = cluster.get("disable")
        if disable:
            return disable.get("integrations", [])
    return []
