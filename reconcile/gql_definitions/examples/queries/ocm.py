"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
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

from reconcile.gql_definitions.examples.fragments.vault_secret import VaultSecret
from reconcile.gql_definitions.examples.fragments.vault_secret_version import VaultSecretVersion
from reconcile.gql_definitions.examples.fragments.vault_secret_path import VaultSecretPath


DEFINITION = """
fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

fragment VaultSecretPath on VaultSecret_v1 {
    path
}

fragment VaultSecretVersion on VaultSecret_v1 {
    version
}

query OCPAuthFull {
  ocp_release_mirror: ocp_release_mirror_v1 {
    hiveCluster {
      name
      ocm {
        name
        offlineToken {
            ... VaultSecret
        }
      }
      automationToken {
        ... VaultSecretVersion
        ... VaultSecretPath
        format
      }
    }
  }
}
"""


class OpenShiftClusterManagerV1(BaseModel):
    name: str = Field(..., alias="name")
    offline_token: Optional[VaultSecret] = Field(..., alias="offlineToken")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1_VaultSecretV1(VaultSecretVersion, VaultSecretPath):
    q_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    ocm: Optional[OpenShiftClusterManagerV1] = Field(..., alias="ocm")
    automation_token: Optional[ClusterV1_VaultSecretV1] = Field(..., alias="automationToken")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OcpReleaseMirrorV1(BaseModel):
    hive_cluster: ClusterV1 = Field(..., alias="hiveCluster")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OCPAuthFullQueryData(BaseModel):
    ocp_release_mirror: Optional[list[OcpReleaseMirrorV1]] = Field(..., alias="ocp_release_mirror")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> OCPAuthFullQueryData:
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
        OCPAuthFullQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, kwargs)
    return OCPAuthFullQueryData(**raw_data)
