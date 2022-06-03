"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611


class AppV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


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


class NamespaceV1_VaultSecretV1(BaseModel):
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


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    console_url: str = Field(..., alias="consoleUrl")
    server_url: str = Field(..., alias="serverUrl")
    insecure_skip_t_l_s_verify: Optional[bool] = Field(..., alias="insecureSkipTLSVerify")
    jump_host: Optional[ClusterJumpHostV1] = Field(..., alias="jumpHost")
    automation_token: Optional[NamespaceV1_VaultSecretV1] = Field(..., alias="automationToken")
    internal: Optional[bool] = Field(..., alias="internal")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    cluster: ClusterV1 = Field(..., alias="cluster")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderTektonObjectTemplateV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderPipelineTemplatesV1(BaseModel):
    openshift_saas_deploy: PipelinesProviderTektonObjectTemplateV1 = Field(..., alias="openshiftSaasDeploy")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderTektonProviderDefaultsV1(BaseModel):
    pipeline_templates: PipelinesProviderPipelineTemplatesV1 = Field(..., alias="pipelineTemplates")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderTektonV1_PipelinesProviderTektonObjectTemplateV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderV1_PipelinesProviderPipelineTemplatesV1(BaseModel):
    openshift_saas_deploy: PipelinesProviderTektonV1_PipelinesProviderTektonObjectTemplateV1 = Field(..., alias="openshiftSaasDeploy")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderTektonV1(PipelinesProviderV1):
    namespace: NamespaceV1 = Field(..., alias="namespace")
    defaults: PipelinesProviderTektonProviderDefaultsV1 = Field(..., alias="defaults")
    pipeline_templates: Optional[PipelinesProviderV1_PipelinesProviderPipelineTemplatesV1] = Field(..., alias="pipelineTemplates")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ResourceRequirementsV1(BaseModel):
    cpu: str = Field(..., alias="cpu")
    memory: str = Field(..., alias="memory")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2_ResourceRequirementsV1(BaseModel):
    cpu: str = Field(..., alias="cpu")
    memory: str = Field(..., alias="memory")

    class Config:
        smart_union = True
        extra = Extra.forbid


class DeployResourcesV1(BaseModel):
    requests: ResourceRequirementsV1 = Field(..., alias="requests")
    limits: SaasFileV2_ResourceRequirementsV1 = Field(..., alias="limits")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackWorkspaceV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackWorkspaceIntegrationV1(BaseModel):
    name: str = Field(..., alias="name")
    token: SlackWorkspaceV1_VaultSecretV1 = Field(..., alias="token")
    channel: str = Field(..., alias="channel")
    icon_emoji: str = Field(..., alias="icon_emoji")
    username: str = Field(..., alias="username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackWorkspaceV1(BaseModel):
    name: str = Field(..., alias="name")
    integrations: Optional[list[SlackWorkspaceIntegrationV1]] = Field(..., alias="integrations")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackOutputNotificationsV1(BaseModel):
    start: Optional[bool] = Field(..., alias="start")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackOutputV1(BaseModel):
    output: Optional[str] = Field(..., alias="output")
    workspace: SlackWorkspaceV1 = Field(..., alias="workspace")
    channel: Optional[str] = Field(..., alias="channel")
    notifications: Optional[SlackOutputNotificationsV1] = Field(..., alias="notifications")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFilesV2XXL_SaasFileV2_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileAuthenticationV1(BaseModel):
    code: Optional[SaasFileV2_VaultSecretV1] = Field(..., alias="code")
    image: Optional[SaasFilesV2XXL_SaasFileV2_VaultSecretV1] = Field(..., alias="image")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFilesV2XXL_SaasFileV2_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: SaasFilesV2XXL_SaasFileV2_VaultSecretV1 = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2_SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: SaasResourceTemplateV2_VaultSecretV1 = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class EnvironmentV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_NamespaceV1_SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: EnvironmentV1_VaultSecretV1 = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class EnvironmentV1(BaseModel):
    name: str = Field(..., alias="name")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasResourceTemplateV2_NamespaceV1_SaasSecretParametersV1]] = Field(..., alias="secretParameters")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2_AppV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2_ClusterV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_NamespaceV1_ClusterJumpHostV1(BaseModel):
    hostname: str = Field(..., alias="hostname")
    known_hosts: str = Field(..., alias="knownHosts")
    user: str = Field(..., alias="user")
    port: Optional[int] = Field(..., alias="port")
    identity: SaasResourceTemplateTargetV2_ClusterV1_VaultSecretV1 = Field(..., alias="identity")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_NamespaceV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2_SaasResourceTemplateV2_NamespaceV1_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_NamespaceV1_DisableClusterAutomationsV1(BaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2_ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    insecure_skip_t_l_s_verify: Optional[bool] = Field(..., alias="insecureSkipTLSVerify")
    jump_host: Optional[SaasResourceTemplateV2_NamespaceV1_ClusterJumpHostV1] = Field(..., alias="jumpHost")
    automation_token: Optional[SaasResourceTemplateV2_NamespaceV1_VaultSecretV1] = Field(..., alias="automationToken")
    cluster_admin_automation_token: Optional[SaasResourceTemplateTargetV2_SaasResourceTemplateV2_NamespaceV1_VaultSecretV1] = Field(..., alias="clusterAdminAutomationToken")
    internal: Optional[bool] = Field(..., alias="internal")
    disable: Optional[SaasResourceTemplateV2_NamespaceV1_DisableClusterAutomationsV1] = Field(..., alias="disable")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    environment: EnvironmentV1 = Field(..., alias="environment")
    app: SaasResourceTemplateTargetV2_AppV1 = Field(..., alias="app")
    cluster: SaasResourceTemplateTargetV2_ClusterV1 = Field(..., alias="cluster")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PromotionChannelDataV1(BaseModel):
    f_type: str = Field(..., alias="type")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ParentSaasPromotionV1(PromotionChannelDataV1):
    parent_saas: Optional[str] = Field(..., alias="parent_saas")
    target_config_hash: Optional[str] = Field(..., alias="target_config_hash")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PromotionDataV1(BaseModel):
    channel: Optional[str] = Field(..., alias="channel")
    data: Optional[list[Union[ParentSaasPromotionV1, PromotionChannelDataV1]]] = Field(..., alias="data")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetPromotionV1(BaseModel):
    auto: Optional[bool] = Field(..., alias="auto")
    publish: Optional[list[str]] = Field(..., alias="publish")
    subscribe: Optional[list[str]] = Field(..., alias="subscribe")
    promotion_data: Optional[list[PromotionDataV1]] = Field(..., alias="promotion_data")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2_VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2_SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: SaasResourceTemplateTargetV2_VaultSecretV1 = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsInstanceV1(BaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetUpstreamV1(BaseModel):
    instance: JenkinsInstanceV1 = Field(..., alias="instance")
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2(BaseModel):
    namespace: SaasResourceTemplateV2_NamespaceV1 = Field(..., alias="namespace")
    ref: str = Field(..., alias="ref")
    promotion: Optional[SaasResourceTemplateTargetPromotionV1] = Field(..., alias="promotion")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasResourceTemplateV2_SaasSecretParametersV1]] = Field(..., alias="secretParameters")
    upstream: Optional[SaasResourceTemplateTargetUpstreamV1] = Field(..., alias="upstream")
    disable: Optional[bool] = Field(..., alias="disable")
    delete: Optional[bool] = Field(..., alias="delete")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2(BaseModel):
    name: str = Field(..., alias="name")
    url: str = Field(..., alias="url")
    path: str = Field(..., alias="path")
    provider: Optional[str] = Field(..., alias="provider")
    hash_length: Optional[int] = Field(..., alias="hash_length")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasFileV2_SaasSecretParametersV1]] = Field(..., alias="secretParameters")
    targets: Optional[list[SaasResourceTemplateTargetV2]] = Field(..., alias="targets")

    class Config:
        smart_union = True
        extra = Extra.forbid


class UserV1(BaseModel):
    org_username: str = Field(..., alias="org_username")
    tag_on_merge_requests: Optional[bool] = Field(..., alias="tag_on_merge_requests")

    class Config:
        smart_union = True
        extra = Extra.forbid


class RoleV1(BaseModel):
    users: Optional[list[UserV1]] = Field(..., alias="users")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2(BaseModel):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    app: AppV1 = Field(..., alias="app")
    pipelines_provider: Union[PipelinesProviderTektonV1, PipelinesProviderV1] = Field(..., alias="pipelinesProvider")
    deploy_resources: Optional[DeployResourcesV1] = Field(..., alias="deployResources")
    slack: Optional[SlackOutputV1] = Field(..., alias="slack")
    managed_resource_types: Optional[list[str]] = Field(..., alias="managedResourceTypes")
    takeover: Optional[bool] = Field(..., alias="takeover")
    compare: Optional[bool] = Field(..., alias="compare")
    publish_job_logs: Optional[bool] = Field(..., alias="publishJobLogs")
    cluster_admin: Optional[bool] = Field(..., alias="clusterAdmin")
    image_patterns: Optional[list[str]] = Field(..., alias="imagePatterns")
    use_channel_in_image_tag: Optional[bool] = Field(..., alias="use_channel_in_image_tag")
    authentication: Optional[SaasFileAuthenticationV1] = Field(..., alias="authentication")
    parameters: Optional[Json] = Field(..., alias="parameters")
    secret_parameters: Optional[list[SaasSecretParametersV1]] = Field(..., alias="secretParameters")
    resource_templates: Optional[list[SaasResourceTemplateV2]] = Field(..., alias="resourceTemplates")
    roles: Optional[list[RoleV1]] = Field(..., alias="roles")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFilesV2XXLQuery(BaseModel):
    saas_files_v2: Optional[list[SaasFileV2]] = Field(..., alias="saas_files")

    class Config:
        smart_union = True
        extra = Extra.forbid
