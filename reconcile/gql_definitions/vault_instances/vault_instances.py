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

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query VaultInstances {
  vault_instances: vault_instances_v1 {
    name
    address
    auth {
      provider
      secretEngine
      ... on VaultInstanceAuthApprole_v1 {
      roleID {
        ... VaultSecret
      }
      secretID {
        ... VaultSecret
      }
    }
    }
    replication {
      vaultInstance {
        name
        address
        auth {
            provider
            secretEngine
            ... on VaultInstanceAuthApprole_v1 {
              roleID {
                ... VaultSecret
              }
              secretID {
                ... VaultSecret
              }
            }
          }
      }
    sourceAuth {
      provider
      secretEngine
      ... on VaultInstanceAuthApprole_v1 {
      roleID {
        ... VaultSecret
      }
      secretID {
        ... VaultSecret
      }
    }
    }
    destAuth {
      provider
      secretEngine
      ... on VaultInstanceAuthApprole_v1 {
      roleID {
        ... VaultSecret
      }
      secretID {
        ... VaultSecret
      }
    }
    }
      paths {
        provider
        ...on VaultReplicationJenkins_v1 {
        jenkinsInstance {
          name
          serverUrl
        }
        policy {
          name
          instance {
            name
            address
          }
        }
        }
        ...on VaultReplicationPolicy_v1 {
          policy {
              name
              instance {
                name
                address
              }
          }
        }
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultInstanceAuthV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    secret_engine: str = Field(..., alias="secretEngine")


class VaultInstanceAuthApproleV1(VaultInstanceAuthV1):
    role_id: VaultSecret = Field(..., alias="roleID")
    secret_id: VaultSecret = Field(..., alias="secretID")


class VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    secret_engine: str = Field(..., alias="secretEngine")


class VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1(
    VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1
):
    role_id: VaultSecret = Field(..., alias="roleID")
    secret_id: VaultSecret = Field(..., alias="secretID")


class VaultReplicationConfigV1_VaultInstanceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    address: str = Field(..., alias="address")
    auth: Union[
        VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
        VaultReplicationConfigV1_VaultInstanceV1_VaultInstanceAuthV1,
    ] = Field(..., alias="auth")


class VaultReplicationConfigV1_VaultInstanceAuthV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    secret_engine: str = Field(..., alias="secretEngine")


class VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1(
    VaultReplicationConfigV1_VaultInstanceAuthV1
):
    role_id: VaultSecret = Field(..., alias="roleID")
    secret_id: VaultSecret = Field(..., alias="secretID")


class VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    secret_engine: str = Field(..., alias="secretEngine")


class VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1(
    VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1
):
    role_id: VaultSecret = Field(..., alias="roleID")
    secret_id: VaultSecret = Field(..., alias="secretID")


class VaultReplicationPathsV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")


class JenkinsInstanceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")


class VaultPolicyV1_VaultInstanceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    address: str = Field(..., alias="address")


class VaultPolicyV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    instance: VaultPolicyV1_VaultInstanceV1 = Field(..., alias="instance")


class VaultReplicationJenkinsV1(VaultReplicationPathsV1):
    jenkins_instance: JenkinsInstanceV1 = Field(..., alias="jenkinsInstance")
    policy: Optional[VaultPolicyV1] = Field(..., alias="policy")


class VaultReplicationPolicyV1_VaultPolicyV1_VaultInstanceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    address: str = Field(..., alias="address")


class VaultReplicationPolicyV1_VaultPolicyV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    instance: VaultReplicationPolicyV1_VaultPolicyV1_VaultInstanceV1 = Field(
        ..., alias="instance"
    )


class VaultReplicationPolicyV1(VaultReplicationPathsV1):
    policy: Optional[VaultReplicationPolicyV1_VaultPolicyV1] = Field(
        ..., alias="policy"
    )


class VaultReplicationConfigV1(ConfiguredBaseModel):
    vault_instance: VaultReplicationConfigV1_VaultInstanceV1 = Field(
        ..., alias="vaultInstance"
    )
    source_auth: Union[
        VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
        VaultReplicationConfigV1_VaultInstanceAuthV1,
    ] = Field(..., alias="sourceAuth")
    dest_auth: Union[
        VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1_VaultInstanceAuthApproleV1,
        VaultInstanceV1_VaultReplicationConfigV1_VaultInstanceAuthV1,
    ] = Field(..., alias="destAuth")
    paths: Optional[
        list[
            Union[
                VaultReplicationJenkinsV1,
                VaultReplicationPolicyV1,
                VaultReplicationPathsV1,
            ]
        ]
    ] = Field(..., alias="paths")


class VaultInstanceV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    address: str = Field(..., alias="address")
    auth: Union[VaultInstanceAuthApproleV1, VaultInstanceAuthV1] = Field(
        ..., alias="auth"
    )
    replication: Optional[list[VaultReplicationConfigV1]] = Field(
        ..., alias="replication"
    )


class VaultInstancesQueryData(ConfiguredBaseModel):
    vault_instances: Optional[list[VaultInstanceV1]] = Field(
        ..., alias="vault_instances"
    )


def query(query_func: Callable, **kwargs: Any) -> VaultInstancesQueryData:
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
        VaultInstancesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return VaultInstancesQueryData(**raw_data)
