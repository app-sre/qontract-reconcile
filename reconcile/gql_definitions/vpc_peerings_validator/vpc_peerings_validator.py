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

from reconcile.gql_definitions.vpc_peerings_validator.vpc_peerings_validator_peered_cluster_fragment import VpcPeeringsValidatorPeeredCluster


DEFINITION = """
fragment VpcPeeringsValidatorPeeredCluster on Cluster_v1 {
  name
  network {
    vpc
  }
  spec {
    private
  }
  internal
}

query VpcPeeringsValidator {
  clusters: clusters_v1 {
    name
    network {
      vpc
    }
    spec {
      private
    }
    internal
    peering {
      connections {
        provider
        ... on ClusterPeeringConnectionAccount_v1 {
          vpc {
            cidr_block
            name
          }
        }
        ... on ClusterPeeringConnectionAccountVPCMesh_v1{
          name
          account {
            name
            uid
          }
          tags
        }
        ... on ClusterPeeringConnectionClusterRequester_v1 {
          cluster {
            ... VpcPeeringsValidatorPeeredCluster
          }
        }
        ... on ClusterPeeringConnectionClusterAccepter_v1 {
          cluster {
            ... VpcPeeringsValidatorPeeredCluster
          }
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


class ClusterNetworkV1(ConfiguredBaseModel):
    vpc: str = Field(..., alias="vpc")


class ClusterSpecV1(ConfiguredBaseModel):
    private: bool = Field(..., alias="private")


class ClusterPeeringConnectionV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")


class AWSVPCV1(ConfiguredBaseModel):
    cidr_block: str = Field(..., alias="cidr_block")
    name: str = Field(..., alias="name")


class ClusterPeeringConnectionAccountV1(ClusterPeeringConnectionV1):
    vpc: AWSVPCV1 = Field(..., alias="vpc")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")


class ClusterPeeringConnectionAccountVPCMeshV1(ClusterPeeringConnectionV1):
    name: str = Field(..., alias="name")
    account: AWSAccountV1 = Field(..., alias="account")
    tags: Optional[Json] = Field(..., alias="tags")


class ClusterPeeringConnectionClusterRequesterV1(ClusterPeeringConnectionV1):
    cluster: VpcPeeringsValidatorPeeredCluster = Field(..., alias="cluster")


class ClusterPeeringConnectionClusterAccepterV1(ClusterPeeringConnectionV1):
    cluster: VpcPeeringsValidatorPeeredCluster = Field(..., alias="cluster")


class ClusterPeeringV1(ConfiguredBaseModel):
    connections: list[Union[ClusterPeeringConnectionAccountVPCMeshV1, ClusterPeeringConnectionAccountV1, ClusterPeeringConnectionClusterRequesterV1, ClusterPeeringConnectionClusterAccepterV1, ClusterPeeringConnectionV1]] = Field(..., alias="connections")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    network: Optional[ClusterNetworkV1] = Field(..., alias="network")
    spec: Optional[ClusterSpecV1] = Field(..., alias="spec")
    internal: Optional[bool] = Field(..., alias="internal")
    peering: Optional[ClusterPeeringV1] = Field(..., alias="peering")


class VpcPeeringsValidatorQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> VpcPeeringsValidatorQueryData:
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
        VpcPeeringsValidatorQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return VpcPeeringsValidatorQueryData(**raw_data)
