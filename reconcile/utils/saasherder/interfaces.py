from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from typing import (
    Any,
    Protocol,
    runtime_checkable,
)

from reconcile.utils import oc_connection_parameters
from reconcile.utils.secret_reader import HasSecret


@runtime_checkable
class HasParameters(Protocol):
    parameters: dict[str, Any] | None


class SaasFileSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret: ...

    def dict(
        self,
        *,
        by_alias: bool = False,
        include: AbstractSetIntStr | MappingIntStrAny | None = None,
    ) -> dict[str, Any]: ...


SaasSecretParameters = Sequence[SaasFileSecretParameters] | None
# Taken from pydantic.typing
AbstractSetIntStr = Set[int | str]
MappingIntStrAny = Mapping[int | str, Any]


@runtime_checkable
class HasSecretParameters(Protocol):
    @property
    def secret_parameters(self) -> SaasSecretParameters: ...


class SaasParentApp(Protocol):
    name: str


@runtime_checkable
class SaasApp(Protocol):
    name: str

    @property
    def parent_app(self) -> SaasParentApp | None: ...

    @property
    def self_service_roles(self) -> Sequence[SaasRole] | None: ...

    @property
    def service_owners(self) -> Sequence[SaasServiceOwner] | None: ...

    @property
    def code_components(self) -> Sequence[AppCodeComponent] | None: ...


class SaasPipelinesProvider(Protocol):
    name: str
    provider: str


class SaasPipelinesProviderTektonNamespaceCluster(
    oc_connection_parameters.Cluster, Protocol
):
    console_url: str


class SaasPipelinesProviderTektonNamespace(Protocol):
    name: str

    @property
    def cluster(self) -> SaasPipelinesProviderTektonNamespaceCluster: ...


class SaasPipelinesProviderTektonObjectTemplate(Protocol):
    name: str


class SaasPipelinesProviderPipelineTemplates(Protocol):
    @property
    def openshift_saas_deploy(self) -> SaasPipelinesProviderTektonObjectTemplate: ...


class SaasPipelinesProviderTektonProviderDefaults(Protocol):
    @property
    def pipeline_templates(self) -> SaasPipelinesProviderPipelineTemplates: ...


class SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates_PipelinesProviderTektonObjectTemplate(
    Protocol
):
    name: str


class SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates(Protocol):
    @property
    def openshift_saas_deploy(
        self,
    ) -> SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates_PipelinesProviderTektonObjectTemplate: ...


@runtime_checkable
class SaasPipelinesProviderTekton(Protocol):
    name: str
    provider: str

    @property
    def namespace(self) -> SaasPipelinesProviderTektonNamespace: ...

    @property
    def defaults(self) -> SaasPipelinesProviderTektonProviderDefaults: ...

    @property
    def pipeline_templates(
        self,
    ) -> SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates | None: ...


class SaasResourceRequestsRequirements(Protocol):
    cpu: str
    memory: str


class SaasResourceLimitsRequirements(Protocol):
    cpu: str | None
    memory: str


class SaasDeployResources(Protocol):
    @property
    def requests(self) -> SaasResourceRequestsRequirements: ...

    @property
    def limits(self) -> SaasResourceLimitsRequirements: ...


class SaasSlackWorkspaceIntegration(Protocol):
    name: str
    channel: str
    icon_emoji: str
    username: str

    @property
    def token(self) -> HasSecret: ...


class SaasSlackWorkspace(Protocol):
    name: str

    @property
    def integrations(self) -> Sequence[SaasSlackWorkspaceIntegration] | None: ...


class SaasSlackOutputNotifications(Protocol):
    start: bool | None


class SaasSlackOutput(Protocol):
    output: str | None
    channel: str | None

    @property
    def workspace(self) -> SaasSlackWorkspace: ...

    @property
    def notifications(self) -> SaasSlackOutputNotifications | None: ...


class SaasFileAuthentication(Protocol):
    @property
    def code(self) -> HasSecret | None: ...

    @property
    def image(self) -> HasSecret | None: ...


class SaasEnvironment_SaasSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret: ...


@runtime_checkable
class SaasEnvironment(HasParameters, HasSecretParameters, Protocol):
    name: str


class SaasResourceTemplateTargetNamespace(Protocol):
    name: str

    @property
    def environment(self) -> SaasEnvironment: ...

    @property
    def app(self) -> SaasApp: ...

    @property
    def cluster(self) -> oc_connection_parameters.Cluster: ...

    def dict(
        self,
        *,
        by_alias: bool = False,
        include: AbstractSetIntStr | MappingIntStrAny | None = None,
    ) -> dict[str, Any]: ...


class SaasPromotionChannelData(Protocol):
    q_type: str


@runtime_checkable
class SaasParentSaasPromotion(Protocol):
    q_type: str
    parent_saas: str | None
    target_config_hash: str | None


class SaasPromotionData(Protocol):
    channel: str | None

    @property
    def data(
        self,
    ) -> Sequence[SaasParentSaasPromotion | SaasPromotionChannelData] | None: ...


class SaasResourceTemplateTargetPromotion(Protocol):
    auto: bool | None
    publish: list[str] | None
    subscribe: list[str] | None
    soak_days: int | None

    @property
    def promotion_data(self) -> Sequence[SaasPromotionData] | None: ...


class Channel(Protocol):
    name: str
    publisher_uids: list[str]


@runtime_checkable
class SaasPromotion(Protocol):
    commit_sha: str
    saas_file: str
    target_config_hash: str
    auto: bool | None = None
    publish: list[str] | None = None
    saas_file_paths: list[str] | None = None
    target_paths: list[str] | None = None
    soak_days: int | None = None

    @property
    def promotion_data(self) -> Sequence[SaasPromotionData] | None: ...

    @property
    def subscribe(self) -> list[Channel] | None: ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class SaasResourceTemplateTarget_SaasSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret: ...


class SaasJenkinsInstance(Protocol):
    name: str
    server_url: str


class SaasResourceTemplateTargetUpstream(Protocol):
    name: str

    @property
    def instance(self) -> SaasJenkinsInstance: ...


class SaasQuayInstance(Protocol):
    url: str


class SaasQuayOrg(Protocol):
    name: str

    @property
    def instance(self) -> SaasQuayInstance: ...


class SaasResourceTemplateTargetImage(Protocol):
    name: str

    @property
    def org(self) -> SaasQuayOrg: ...


class SaasResourceTemplateTarget(HasParameters, HasSecretParameters, Protocol):
    path: str | None
    name: str | None
    disable: bool | None
    delete: bool | None
    ref: str

    @property
    def namespace(self) -> SaasResourceTemplateTargetNamespace: ...

    @property
    def promotion(self) -> SaasResourceTemplateTargetPromotion | None: ...

    @property
    def upstream(self) -> SaasResourceTemplateTargetUpstream | None: ...

    @property
    def image(self) -> SaasResourceTemplateTargetImage | None: ...

    def uid(
        self, parent_saas_file_name: str, parent_resource_template_name: str
    ) -> str: ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]: ...


class SaasResourceTemplate(HasParameters, HasSecretParameters, Protocol):
    name: str
    url: str
    path: str
    provider: str | None
    hash_length: int | None

    @property
    def targets(self) -> Sequence[SaasResourceTemplateTarget]: ...


class SaasRole(Protocol):
    name: str


class SaasServiceOwner(Protocol):
    name: str
    email: str


class AppCodeComponent(Protocol):
    url: str
    blocked_versions: list[str] | None
    hotfix_versions: list[str] | None


SaasPipelinesProviders = SaasPipelinesProviderTekton | SaasPipelinesProvider


@runtime_checkable
class ManagedResourceName(Protocol):
    resource: str
    resource_names: list[str]


class SaasFile(HasParameters, HasSecretParameters, Protocol):
    path: str
    name: str
    labels: dict[str, Any] | None
    managed_resource_types: list[str]
    takeover: bool | None
    deprecated: bool | None
    compare: bool | None
    timeout: str | None
    publish_job_logs: bool | None
    cluster_admin: bool | None
    image_patterns: list[str]
    allowed_secret_parameter_paths: list[str] | None
    use_channel_in_image_tag: bool | None
    validate_targets_in_app: bool | None

    @property
    def app(self) -> SaasApp: ...

    @property
    def pipelines_provider(self) -> SaasPipelinesProviders: ...

    @property
    def deploy_resources(self) -> SaasDeployResources | None: ...

    @property
    def slack(self) -> SaasSlackOutput | None: ...

    @property
    def authentication(self) -> SaasFileAuthentication | None: ...

    @property
    def resource_templates(self) -> Sequence[SaasResourceTemplate]: ...

    @property
    def self_service_roles(self) -> Sequence[SaasRole] | None: ...

    @property
    def managed_resource_names(self) -> Sequence[ManagedResourceName] | None: ...
