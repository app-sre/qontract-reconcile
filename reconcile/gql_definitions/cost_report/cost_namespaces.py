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
query CostNamespaces {
  namespaces: namespaces_v1 {
    name
    app {
      name
    }
    cluster {
      name
      spec {
        external_id
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class AppV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")


class ClusterSpecV1(ConfiguredBaseModel):
    external_id: Optional[str] = Field(..., alias="external_id")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    spec: Optional[ClusterSpecV1] = Field(..., alias="spec")


class NamespaceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    app: AppV1 = Field(..., alias="app")
    cluster: ClusterV1 = Field(..., alias="cluster")


class CostNamespacesQueryData(ConfiguredBaseModel):
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")


def query(query_func: Callable, **kwargs: Any) -> CostNamespacesQueryData:
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
        CostNamespacesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return CostNamespacesQueryData(**raw_data)
