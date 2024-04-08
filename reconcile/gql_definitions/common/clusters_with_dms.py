"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from collections.abc import Callable  # noqa: F401 # pylint: disable=W0611
from datetime import datetime  # noqa: F401 # pylint: disable=W0611
from enum import Enum  # noqa: F401 # pylint: disable=W0611
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


DEFINITION = """
query ClustersWithMonitoring($filter: JSON){
  clusters: clusters_v1(filter: $filter) {
    name
    serverUrl
    consoleUrl
    alertmanagerUrl
    prometheusUrl
    managedClusterRoles
    enableDeadMansSnitch
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    console_url: str = Field(..., alias="consoleUrl")
    alertmanager_url: str = Field(..., alias="alertmanagerUrl")
    prometheus_url: str = Field(..., alias="prometheusUrl")
    managed_cluster_roles: Optional[bool] = Field(..., alias="managedClusterRoles")
    enable_dead_mans_snitch: Optional[bool] = Field(..., alias="enableDeadMansSnitch")


class ClustersWithMonitoringQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> ClustersWithMonitoringQueryData:
    """
    This is a convenience function which queries and parses the data into
    concrete types. It should be compatible with most GQL clients.
    You do not have to use it to consume the generated data classes.
    Alternatively, you can also mime and alternate the behavior
    of this function in the caller.

    Parameters:
        query_func (Callable): Function which queries your GQL Server
        kwargs: optional arguments that will be passed to the query function

    Returns:
        ClustersWithMonitoringQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return ClustersWithMonitoringQueryData(**raw_data)
