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
query AVSNamespaces {
  namespaces: namespaces_v1 {
    path
    name
    delete
    managedExternalResources
    externalResources {
      provider
      provisioner {
        ... on AWSAccount_v1 {
          path
          name
          uid
        }
      }
      ... on NamespaceTerraformProviderResourceAWS_v1 {
        resources {
          provider
          ... on NamespaceTerraformResourceRDS_v1 {
            identifier
            defaults
            overrides
          }
        }
      }
    }
    cluster {
      name
      disable {
        integrations
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class ExternalResourcesProvisionerV1(ConfiguredBaseModel):
    ...


class AWSAccountV1(ExternalResourcesProvisionerV1):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")


class NamespaceExternalResourceV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    provisioner: Union[AWSAccountV1, ExternalResourcesProvisionerV1] = Field(..., alias="provisioner")


class NamespaceTerraformResourceAWSV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")


class NamespaceTerraformResourceRDSV1(NamespaceTerraformResourceAWSV1):
    identifier: str = Field(..., alias="identifier")
    defaults: str = Field(..., alias="defaults")
    overrides: Optional[Json] = Field(..., alias="overrides")


class NamespaceTerraformProviderResourceAWSV1(NamespaceExternalResourceV1):
    resources: list[Union[NamespaceTerraformResourceRDSV1, NamespaceTerraformResourceAWSV1]] = Field(..., alias="resources")


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")


class NamespaceV1(ConfiguredBaseModel):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    delete: Optional[bool] = Field(..., alias="delete")
    managed_external_resources: Optional[bool] = Field(..., alias="managedExternalResources")
    external_resources: Optional[list[Union[NamespaceTerraformProviderResourceAWSV1, NamespaceExternalResourceV1]]] = Field(..., alias="externalResources")
    cluster: ClusterV1 = Field(..., alias="cluster")


class AVSNamespacesQueryData(ConfiguredBaseModel):
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")


def query(query_func: Callable, **kwargs: Any) -> AVSNamespacesQueryData:
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
        AVSNamespacesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return AVSNamespacesQueryData(**raw_data)
