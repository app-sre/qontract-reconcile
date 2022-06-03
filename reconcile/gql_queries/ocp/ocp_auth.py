"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611


class VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterJumpHostV1(BaseModel):
    hostname: str = Field(..., alias="hostname")
    known_hosts: str = Field(..., alias="knownHosts")
    user: str = Field(..., alias="user")
    port: Optional[int] = Field(..., alias="port")
    identity: VaultSecretV1 = Field(..., alias="identity")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OpenShiftClusterManagerV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    f_format: Optional[str] = Field(..., alias="format")
    version: Optional[int] = Field(..., alias="version")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OpenShiftClusterManagerV1(BaseModel):
    name: str = Field(..., alias="name")
    url: str = Field(..., alias="url")
    access_token_client_id: str = Field(..., alias="accessTokenClientId")
    access_token_url: str = Field(..., alias="accessTokenUrl")
    offline_token: Optional[OpenShiftClusterManagerV1_VaultSecretV1] = Field(..., alias="offlineToken")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class DisableClusterAutomationsV1(BaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterAuthV1(BaseModel):
    service: str = Field(..., alias="service")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterAuthGithubOrgV1(ClusterAuthV1):
    org: str = Field(..., alias="org")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterAuthGithubOrgTeamV1(ClusterAuthV1):
    org: str = Field(..., alias="org")
    team: str = Field(..., alias="team")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    insecure_skip_t_l_s_verify: Optional[bool] = Field(..., alias="insecureSkipTLSVerify")
    jump_host: Optional[ClusterJumpHostV1] = Field(..., alias="jumpHost")
    managed_groups: Optional[list[str]] = Field(..., alias="managedGroups")
    ocm: Optional[OpenShiftClusterManagerV1] = Field(..., alias="ocm")
    automation_token: Optional[ClusterV1_VaultSecretV1] = Field(..., alias="automationToken")
    internal: Optional[bool] = Field(..., alias="internal")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")
    auth: Optional[Union[ClusterAuthGithubOrgTeamV1, ClusterAuthGithubOrgV1, ClusterAuthV1]] = Field(..., alias="auth")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformResourceAWSV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformResourceECRV1(NamespaceTerraformResourceAWSV1):
    account: str = Field(..., alias="account")
    region: Optional[str] = Field(..., alias="region")
    identifier: str = Field(..., alias="identifier")
    output_resource_name: Optional[str] = Field(..., alias="output_resource_name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1_ClusterV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1_ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    automation_token: Optional[NamespaceV1_ClusterV1_VaultSecretV1] = Field(..., alias="automationToken")
    internal: Optional[bool] = Field(..., alias="internal")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    managed_terraform_resources: Optional[bool] = Field(..., alias="managedTerraformResources")
    terraform_resources: Optional[list[Union[NamespaceTerraformResourceECRV1, NamespaceTerraformResourceAWSV1]]] = Field(..., alias="terraformResources")
    cluster: NamespaceV1_ClusterV1 = Field(..., alias="cluster")

    class Config:
        smart_union = True
        extra = Extra.forbid


class QuayInstanceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class QuayOrgV1(BaseModel):
    name: str = Field(..., alias="name")
    instance: QuayInstanceV1 = Field(..., alias="instance")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OcpReleaseMirrorV1(BaseModel):
    hive_cluster: ClusterV1 = Field(..., alias="hiveCluster")
    ecr_resources_namespace: NamespaceV1 = Field(..., alias="ecrResourcesNamespace")
    quay_target_orgs: Optional[list[QuayOrgV1]] = Field(..., alias="quayTargetOrgs")
    ocp_release_ecr_identifier: str = Field(..., alias="ocpReleaseEcrIdentifier")
    ocp_art_dev_ecr_identifier: str = Field(..., alias="ocpArtDevEcrIdentifier")
    mirror_channels: Optional[list[str]] = Field(..., alias="mirrorChannels")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OCPAuthFullQuery(BaseModel):
    ocp_release_mirror_v1: Optional[list[OcpReleaseMirrorV1]] = Field(..., alias="ocp_release_mirror")

    class Config:
        smart_union = True
        extra = Extra.forbid
