import base64
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from github import Github
from pydantic import (
    BaseModel,
    Field,
)

from reconcile.utils.oc_connection_parameters import Cluster
from reconcile.utils.saasherder.interfaces import (
    ManagedResourceName,
    SaasApp,
    SaasEnvironment,
    SaasFile,
    SaasPipelinesProviders,
    SaasResourceTemplate,
    SaasResourceTemplateTarget,
)


class Providers(Enum):
    TEKTON = "tekton"


class TriggerTypes:
    CONFIGS = 0
    MOVING_COMMITS = 1
    UPSTREAM_JOBS = 2
    CONTAINER_IMAGES = 3


@dataclass
class UpstreamJob:
    instance: str
    job: str

    def __str__(self) -> str:
        return f"{self.instance}/{self.job}"

    def __repr__(self) -> str:
        return self.__str__()


@dataclass
class TriggerSpecBase:
    saas_file_name: str
    env_name: str
    timeout: str | None
    pipelines_provider: SaasPipelinesProviders
    resource_template_name: str
    cluster_name: str
    namespace_name: str
    state_content: Any

    @property
    def state_key(self) -> str:
        raise NotImplementedError("implement this function in inheriting classes")


@dataclass
class TriggerSpecConfig(TriggerSpecBase):
    target_name: str | None = None
    reason: str | None = None

    @property
    def state_key(self) -> str:
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}"
        )
        if self.target_name:
            key += f"/{self.target_name}"
        return key


@dataclass
class TriggerSpecMovingCommit(TriggerSpecBase):
    ref: str
    reason: str | None = None

    @property
    def state_key(self) -> str:
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.ref}"
        )
        return key


@dataclass
class TriggerSpecUpstreamJob(TriggerSpecBase):
    instance_name: str
    job_name: str
    reason: str | None = None

    @property
    def state_key(self) -> str:
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.instance_name}/{self.job_name}"
        )
        return key


@dataclass
class TriggerSpecContainerImage(TriggerSpecBase):
    image: str
    reason: str | None = None

    @property
    def state_key(self) -> str:
        key = (
            f"{self.saas_file_name}/{self.resource_template_name}/{self.cluster_name}/"
            f"{self.namespace_name}/{self.env_name}/{self.image}"
        )
        return key


TriggerSpecUnion = (
    TriggerSpecConfig
    | TriggerSpecMovingCommit
    | TriggerSpecUpstreamJob
    | TriggerSpecContainerImage
)


class Namespace(BaseModel):
    name: str
    environment: SaasEnvironment
    app: SaasApp
    cluster: Cluster
    managed_resource_types: list[str] = Field(..., alias="managedResourceTypes")
    managed_resource_names: Sequence[ManagedResourceName] | None = Field(
        ..., alias="managedResourceNames"
    )

    class Config:
        arbitrary_types_allowed = True
        allow_population_by_field_name = True


class PromotionChannelData(BaseModel):
    q_type: str = Field(..., alias="type")

    class Config:
        allow_population_by_field_name = True


class ParentSaasPromotion(BaseModel):
    q_type: str = Field(..., alias="type")
    parent_saas: str | None
    target_config_hash: str | None

    class Config:
        allow_population_by_field_name = True


class PromotionData(BaseModel):
    channel: str | None
    data: list[ParentSaasPromotion | PromotionChannelData] | None = None


class Channel(BaseModel):
    name: str
    publisher_uids: list[str]


class Promotion(BaseModel):
    """Implementation of the SaasPromotion interface for saasherder and AutoPromoter."""

    url: str
    commit_sha: str
    saas_file: str
    target_config_hash: str
    saas_target_uid: str
    soak_days: int
    auto: bool | None = None
    publish: list[str] | None = None
    subscribe: list[Channel] | None = None
    promotion_data: list[PromotionData] | None = None
    saas_file_paths: list[str] | None = None
    target_paths: list[str] | None = None


@dataclass
class ImageAuth:
    username: str | None = None
    password: str | None = None
    auth_server: str | None = None
    docker_config: dict[str, dict[str, dict[str, str]]] | None = None

    def getDockerConfigJson(self) -> dict:
        if self.docker_config:
            return self.docker_config
        else:
            return {
                "auths": {
                    self.auth_server: {
                        "auth": base64.b64encode(
                            f"{self.username}:{self.password}".encode()
                        ).decode(),
                    }
                }
            }


@dataclass
class TargetSpec:
    saas_file: SaasFile
    resource_template: SaasResourceTemplate
    target: SaasResourceTemplateTarget
    image_auth: ImageAuth
    hash_length: int
    parameters: dict[str, str]
    github: Github
    target_config_hash: str

    @property
    def saas_file_name(self) -> str:
        return self.saas_file.name

    @property
    def managed_resource_types(self) -> Iterable[str]:
        return self.saas_file.managed_resource_types

    @property
    def managed_resource_names(self) -> Sequence[ManagedResourceName] | None:
        return self.saas_file.managed_resource_names

    @property
    def privileged(self) -> bool:
        return bool(self.saas_file.cluster_admin)

    @property
    def image_patterns(self) -> list[str]:
        return self.saas_file.image_patterns

    @property
    def resource_template_name(self) -> str:
        return self.resource_template.name

    @property
    def url(self) -> str:
        return self.resource_template.url

    @property
    def path(self) -> str:
        return self.resource_template.path

    @property
    def provider(self) -> str:
        return self.resource_template.provider or "openshift-template"

    @property
    def cluster(self) -> str:
        return self.target.namespace.cluster.name

    @property
    def namespace(self) -> str:
        return self.target.namespace.name

    @property
    def delete(self) -> bool:
        return bool(self.target.delete)
