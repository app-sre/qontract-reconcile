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

from reconcile.gql_definitions.fragments.jumphost_common_fields import CommonJumphostFields
from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class SaasSecretParametersV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    secret: VaultSecret = Field(..., alias="secret")


class EnvironmentV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    labels: Optional[Json] = Field(..., alias="labels")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasSecretParametersV1]] = Field(..., alias="secretParameters")


class AppV1_AppV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")


class RoleV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")


class OwnerV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    email: str = Field(..., alias="email")


class AppCodeComponentsV1(ConfiguredBaseModel):
    url: str = Field(..., alias="url")
    blocked_versions: Optional[list[str]] = Field(..., alias="blockedVersions")
    hotfix_versions: Optional[list[str]] = Field(..., alias="hotfixVersions")


class AppV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    parent_app: Optional[AppV1_AppV1] = Field(..., alias="parentApp")
    labels: Optional[Json] = Field(..., alias="labels")
    self_service_roles: Optional[list[RoleV1]] = Field(..., alias="selfServiceRoles")
    service_owners: Optional[list[OwnerV1]] = Field(..., alias="serviceOwners")
    code_components: Optional[list[AppCodeComponentsV1]] = Field(..., alias="codeComponents")


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class ClusterSpecV1(ConfiguredBaseModel):
    region: str = Field(..., alias="region")


class ClusterExternalConfigurationV1(ConfiguredBaseModel):
    labels: Json = Field(..., alias="labels")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    internal: Optional[bool] = Field(..., alias="internal")
    insecure_skip_tls_verify: Optional[bool] = Field(..., alias="insecureSkipTLSVerify")
    labels: Optional[Json] = Field(..., alias="labels")
    jump_host: Optional[CommonJumphostFields] = Field(..., alias="jumpHost")
    automation_token: Optional[VaultSecret] = Field(..., alias="automationToken")
    cluster_admin_automation_token: Optional[VaultSecret] = Field(..., alias="clusterAdminAutomationToken")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")
    spec: Optional[ClusterSpecV1] = Field(..., alias="spec")
    external_configuration: Optional[ClusterExternalConfigurationV1] = Field(..., alias="externalConfiguration")


class NamespaceSkupperSiteConfigV1(ConfiguredBaseModel):
    delete: Optional[bool] = Field(..., alias="delete")


class SaasTargetNamespace(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    labels: Optional[Json] = Field(..., alias="labels")
    delete: Optional[bool] = Field(..., alias="delete")
    path: str = Field(..., alias="path")
    environment: EnvironmentV1 = Field(..., alias="environment")
    app: AppV1 = Field(..., alias="app")
    cluster: ClusterV1 = Field(..., alias="cluster")
    skupper_site: Optional[NamespaceSkupperSiteConfigV1] = Field(..., alias="skupperSite")
