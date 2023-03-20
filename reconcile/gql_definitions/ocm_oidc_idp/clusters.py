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

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment OCMEnvironment on OpenShiftClusterManagerEnvironment_v1 {
    name
    url
    accessTokenClientId
    accessTokenUrl
    accessTokenClientSecret {
        ... VaultSecret
    }
}

fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query OidcClusters($name: String) {
  clusters: clusters_v1(name: $name) {
    name
    ocm {
      name
      environment {
        ... OCMEnvironment
      }
      orgId
      accessTokenClientId
      accessTokenUrl
      accessTokenClientSecret {
        ...VaultSecret
      }
      blockedVersions
      sectors {
        name
        dependencies {
          name
          ocm {
            name
          }
        }
      }
    }
    upgradePolicy {
      workloads
      schedule
      conditions {
        sector
      }
    }
    disable {
      integrations
    }
    auth {
      service
      ... on ClusterAuthOIDC_v1 {
        name
        issuer
        claims {
          email
          name
          username
          groups
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


class OpenShiftClusterManagerSectorDependenciesV1_OpenShiftClusterManagerV1(
    ConfiguredBaseModel
):
    name: str = Field(..., alias="name")


class OpenShiftClusterManagerSectorDependenciesV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    ocm: Optional[
        OpenShiftClusterManagerSectorDependenciesV1_OpenShiftClusterManagerV1
    ] = Field(..., alias="ocm")


class OpenShiftClusterManagerSectorV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    dependencies: Optional[list[OpenShiftClusterManagerSectorDependenciesV1]] = Field(
        ..., alias="dependencies"
    )


class OpenShiftClusterManagerV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    environment: OCMEnvironment = Field(..., alias="environment")
    org_id: str = Field(..., alias="orgId")
    access_token_client_id: Optional[str] = Field(..., alias="accessTokenClientId")
    access_token_url: Optional[str] = Field(..., alias="accessTokenUrl")
    access_token_client_secret: Optional[VaultSecret] = Field(
        ..., alias="accessTokenClientSecret"
    )
    blocked_versions: Optional[list[str]] = Field(..., alias="blockedVersions")
    sectors: Optional[list[OpenShiftClusterManagerSectorV1]] = Field(
        ..., alias="sectors"
    )


class ClusterUpgradePolicyConditionsV1(ConfiguredBaseModel):
    sector: Optional[str] = Field(..., alias="sector")


class ClusterUpgradePolicyV1(ConfiguredBaseModel):
    workloads: list[str] = Field(..., alias="workloads")
    schedule: str = Field(..., alias="schedule")
    conditions: ClusterUpgradePolicyConditionsV1 = Field(..., alias="conditions")


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class ClusterAuthV1(ConfiguredBaseModel):
    service: str = Field(..., alias="service")


class ClusterAuthOIDCClaimsV1(ConfiguredBaseModel):
    email: Optional[list[str]] = Field(..., alias="email")
    name: Optional[list[str]] = Field(..., alias="name")
    username: Optional[list[str]] = Field(..., alias="username")
    groups: Optional[list[str]] = Field(..., alias="groups")


class ClusterAuthOIDCV1(ClusterAuthV1):
    name: str = Field(..., alias="name")
    issuer: Optional[str] = Field(..., alias="issuer")
    claims: Optional[ClusterAuthOIDCClaimsV1] = Field(..., alias="claims")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    ocm: Optional[OpenShiftClusterManagerV1] = Field(..., alias="ocm")
    upgrade_policy: Optional[ClusterUpgradePolicyV1] = Field(..., alias="upgradePolicy")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")
    auth: list[Union[ClusterAuthOIDCV1, ClusterAuthV1]] = Field(..., alias="auth")


class OidcClustersQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> OidcClustersQueryData:
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
        OidcClustersQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return OidcClustersQueryData(**raw_data)
