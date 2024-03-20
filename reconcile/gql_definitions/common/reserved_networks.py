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
query ReservedNetworks {
  networks: network_v1 {
    name
    networkAddress
    parentNetwork {
      networkAddress
    }
    inUseBy {
      vpc{
        name
        account {
          name
          uid
          consoleUrl
        }
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class NetworkV1_NetworkV1(ConfiguredBaseModel):
    network_address: str = Field(..., alias="networkAddress")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")
    console_url: str = Field(..., alias="consoleUrl")


class VPCRequestV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    account: AWSAccountV1 = Field(..., alias="account")


class NetworkInUseByV1(ConfiguredBaseModel):
    vpc: Optional[VPCRequestV1] = Field(..., alias="vpc")


class NetworkV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    network_address: str = Field(..., alias="networkAddress")
    parent_network: Optional[NetworkV1_NetworkV1] = Field(..., alias="parentNetwork")
    in_use_by: Optional[NetworkInUseByV1] = Field(..., alias="inUseBy")


class ReservedNetworksQueryData(ConfiguredBaseModel):
    networks: Optional[list[NetworkV1]] = Field(..., alias="networks")


def query(query_func: Callable, **kwargs: Any) -> ReservedNetworksQueryData:
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
        ReservedNetworksQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return ReservedNetworksQueryData(**raw_data)
