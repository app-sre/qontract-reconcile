from __future__ import annotations

from collections.abc import Sequence
from typing import (
    AbstractSet,
    Any,
    Mapping,
    Optional,
    Protocol,
    Union,
    runtime_checkable,
)

from reconcile.utils import oc_connection_parameters
from reconcile.utils.secret_reader import HasSecret


class HasParameters(Protocol):
    parameters: Optional[dict[str, Any]]


class SaasFileSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret:
        ...

    def dict(
        self,
        *,
        by_alias: bool = False,
        include: Optional[Union[AbstractSetIntStr, MappingIntStrAny]] = None,
    ) -> dict[str, Any]:
        ...


SaasSecretParameters = Optional[Sequence[SaasFileSecretParameters]]
# Taken from pydantic.typing
AbstractSetIntStr = AbstractSet[Union[int, str]]
MappingIntStrAny = Mapping[Union[int, str], Any]


class HasSecretParameters(Protocol):
    @property
    def secret_parameters(self) -> SaasSecretParameters:
        ...


class SaasApp(Protocol):
    name: str


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
    def cluster(self) -> SaasPipelinesProviderTektonNamespaceCluster:
        ...


class SaasPipelinesProviderTektonObjectTemplate(Protocol):
    name: str


class SaasPipelinesProviderPipelineTemplates(Protocol):
    @property
    def openshift_saas_deploy(self) -> SaasPipelinesProviderTektonObjectTemplate:
        ...


class SaasPipelinesProviderTektonProviderDefaults(Protocol):
    @property
    def pipeline_templates(self) -> SaasPipelinesProviderPipelineTemplates:
        ...


class SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates_PipelinesProviderTektonObjectTemplate(
    Protocol
):
    name: str


class SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates(Protocol):
    @property
    def openshift_saas_deploy(
        self,
    ) -> SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates_PipelinesProviderTektonObjectTemplate:
        ...


@runtime_checkable
class SaasPipelinesProviderTekton(Protocol):
    name: str
    provider: str

    @property
    def namespace(self) -> SaasPipelinesProviderTektonNamespace:
        ...

    @property
    def defaults(self) -> SaasPipelinesProviderTektonProviderDefaults:
        ...

    @property
    def pipeline_templates(
        self,
    ) -> Optional[SaasPipelinesProviderTekton_PipelinesProviderPipelineTemplates]:
        ...


class SaasResourceRequirements(Protocol):
    cpu: str
    memory: str


class SaasDeployResources(Protocol):
    @property
    def requests(self) -> SaasResourceRequirements:
        ...

    @property
    def limits(self) -> SaasResourceRequirements:
        ...


class SaasSlackWorkspaceIntegration(Protocol):
    name: str
    channel: str
    icon_emoji: str
    username: str

    @property
    def token(self) -> HasSecret:
        ...


class SaasSlackWorkspace(Protocol):
    name: str

    @property
    def integrations(self) -> Optional[Sequence[SaasSlackWorkspaceIntegration]]:
        ...


class SaasSlackOutputNotifications(Protocol):
    start: Optional[bool]


class SaasSlackOutput(Protocol):
    output: Optional[str]
    channel: Optional[str]

    @property
    def workspace(self) -> SaasSlackWorkspace:
        ...

    @property
    def notifications(self) -> Optional[SaasSlackOutputNotifications]:
        ...


class SaasFileAuthentication(Protocol):
    @property
    def code(self) -> Optional[HasSecret]:
        ...

    @property
    def image(self) -> Optional[HasSecret]:
        ...


class SaasEnvironment_SaasSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret:
        ...


class SaasEnvironment(HasParameters, HasSecretParameters, Protocol):
    name: str


class SaasResourceTemplateTargetNamespace(Protocol):
    name: str

    @property
    def environment(self) -> SaasEnvironment:
        ...

    @property
    def app(self) -> SaasApp:
        ...

    @property
    def cluster(self) -> oc_connection_parameters.Cluster:
        ...

    def dict(
        self,
        *,
        by_alias: bool = False,
        include: Optional[Union[AbstractSetIntStr, MappingIntStrAny]] = None,
    ) -> dict[str, Any]:
        ...


class SaasPromotionChannelData(Protocol):
    q_type: str


@runtime_checkable
class SaasParentSaasPromotion(Protocol):
    q_type: str
    parent_saas: Optional[str]
    target_config_hash: Optional[str]


class SaasPromotionData(Protocol):
    channel: Optional[str]

    @property
    def data(
        self,
    ) -> Optional[Sequence[Union[SaasParentSaasPromotion, SaasPromotionChannelData]]]:
        ...


class SaasResourceTemplateTargetPromotion(Protocol):
    auto: Optional[bool]
    publish: Optional[list[str]]
    subscribe: Optional[list[str]]

    @property
    def promotion_data(self) -> Optional[Sequence[SaasPromotionData]]:
        ...


@runtime_checkable
class SaasPromotion(Protocol):
    commit_sha: str
    saas_file: str
    target_config_hash: str
    auto: Optional[bool] = None
    publish: Optional[list[str]] = None
    subscribe: Optional[list[str]] = None
    saas_file_paths: Optional[list[str]] = None
    target_paths: Optional[list[str]] = None

    @property
    def promotion_data(self) -> Optional[Sequence[SaasPromotionData]]:
        ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]:
        ...


class SaasResourceTemplateTarget_SaasSecretParameters(Protocol):
    name: str

    @property
    def secret(self) -> HasSecret:
        ...


class SaasJenkinsInstance(Protocol):
    name: str
    server_url: str


class SaasResourceTemplateTargetUpstream(Protocol):
    name: str

    @property
    def instance(self) -> SaasJenkinsInstance:
        ...


class SaasQuayInstance(Protocol):
    url: str


class SaasQuayOrg(Protocol):
    name: str

    @property
    def instance(self) -> SaasQuayInstance:
        ...


class SaasResourceTemplateTargetImage(Protocol):
    name: str

    @property
    def org(self) -> SaasQuayOrg:
        ...


class SaasResourceTemplateTarget(HasParameters, HasSecretParameters, Protocol):
    path: Optional[str]
    name: Optional[str]
    disable: Optional[bool]
    delete: Optional[bool]
    ref: str

    @property
    def namespace(self) -> SaasResourceTemplateTargetNamespace:
        ...

    @property
    def promotion(self) -> Optional[SaasResourceTemplateTargetPromotion]:
        ...

    @property
    def upstream(self) -> Optional[SaasResourceTemplateTargetUpstream]:
        ...

    @property
    def image(self) -> Optional[SaasResourceTemplateTargetImage]:
        ...

    def dict(self, *, by_alias: bool = False) -> dict[str, Any]:
        ...


class SaasResourceTemplate(HasParameters, HasSecretParameters, Protocol):
    name: str
    url: str
    path: str
    provider: Optional[str]
    hash_length: Optional[int]

    @property
    def targets(self) -> Sequence[SaasResourceTemplateTarget]:
        ...


class SaasUser(Protocol):
    org_username: str
    tag_on_merge_requests: Optional[bool]


class SaasBot(Protocol):
    org_username: Optional[str]


class SaasRole(Protocol):
    @property
    def users(self) -> Sequence[SaasUser]:
        ...

    @property
    def bots(self) -> Sequence[SaasBot]:
        ...


SaasPipelinesProviders = Union[SaasPipelinesProviderTekton, SaasPipelinesProvider]


class SaasFile(HasParameters, HasSecretParameters, Protocol):
    path: str
    name: str
    managed_resource_types: list[str]
    takeover: Optional[bool]
    deprecated: Optional[bool]
    compare: Optional[bool]
    timeout: Optional[str]
    publish_job_logs: Optional[bool]
    cluster_admin: Optional[bool]
    image_patterns: list[str]
    allowed_secret_parameter_paths: Optional[list[str]]
    use_channel_in_image_tag: Optional[bool]
    validate_targets_in_app: Optional[bool]

    @property
    def app(self) -> SaasApp:
        ...

    @property
    def pipelines_provider(self) -> SaasPipelinesProviders:
        ...

    @property
    def deploy_resources(self) -> Optional[SaasDeployResources]:
        ...

    @property
    def slack(self) -> Optional[SaasSlackOutput]:
        ...

    @property
    def authentication(self) -> Optional[SaasFileAuthentication]:
        ...

    @property
    def resource_templates(self) -> Sequence[SaasResourceTemplate]:
        ...

    @property
    def self_service_roles(self) -> Optional[Sequence[SaasRole]]:
        ...
