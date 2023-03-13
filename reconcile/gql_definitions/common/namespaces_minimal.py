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

from reconcile.gql_definitions.fragments.jumphost_common_fields import (
    CommonJumphostFields,
)
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment CommonJumphostFields on ClusterJumpHost_v1 {
  hostname
  knownHosts
  user
  port
  remotePort
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

query NamespacesMinimal {
  namespaces: namespaces_v1 {
    name
    delete
    labels
    clusterAdmin
    cluster {
      name
      serverUrl
      insecureSkipTLSVerify
      jumpHost {
        ... CommonJumphostFields
      }
      automationToken {
        ... VaultSecret
      }
      clusterAdminAutomationToken {
        ... VaultSecret
      }
      internal
      disable {
        e2eTests
        integrations
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union = True
        extra = Extra.forbid


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    e2e_tests: Optional[list[str]] = Field(..., alias="e2eTests")
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    insecure_skip_tls_verify: Optional[bool] = Field(..., alias="insecureSkipTLSVerify")
    jump_host: Optional[CommonJumphostFields] = Field(..., alias="jumpHost")
    automation_token: Optional[VaultSecret] = Field(..., alias="automationToken")
    cluster_admin_automation_token: Optional[VaultSecret] = Field(
        ..., alias="clusterAdminAutomationToken"
    )
    internal: Optional[bool] = Field(..., alias="internal")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")


class NamespaceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    delete: Optional[bool] = Field(..., alias="delete")
    labels: Optional[Json] = Field(..., alias="labels")
    cluster_admin: Optional[bool] = Field(..., alias="clusterAdmin")
    cluster: ClusterV1 = Field(..., alias="cluster")


class NamespacesMinimalQueryData(ConfiguredBaseModel):
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")


def query(query_func: Callable, **kwargs: Any) -> NamespacesMinimalQueryData:
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
        NamespacesMinimalQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return NamespacesMinimalQueryData(**raw_data)
