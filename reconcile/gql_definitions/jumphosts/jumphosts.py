"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from enum import Enum  # noqa: F401 # pylint: disable=W0611
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Callable,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)

from reconcile.gql_definitions.fragments.jumphost_common_fields import (
    CommonJumphostFields,
)


DEFINITION = """
fragment CommonJumphostFields on ClusterJumpHost_v1 {
  hostname
  knownHosts
  user
  port
  identity {
    ... VaultSecret
  }
}

fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query Jumphosts ($hostname: String) {
  jumphosts: jumphosts_v1 (hostname: $hostname) {
    ... CommonJumphostFields
    clusters {
      name
      network {
        vpc
      }
    }
  }
}
"""


class ClusterNetworkV1(BaseModel):
    vpc: str = Field(..., alias="vpc")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    network: Optional[ClusterNetworkV1] = Field(..., alias="network")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterJumpHostV1(CommonJumphostFields):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JumphostsQueryData(BaseModel):
    jumphosts: Optional[list[ClusterJumpHostV1]] = Field(..., alias="jumphosts")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs: Any) -> JumphostsQueryData:
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
        JumphostsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return JumphostsQueryData(**raw_data)
