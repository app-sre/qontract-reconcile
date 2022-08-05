"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


QUERY: str = """
# qenerate: plugin=pydantic_v1

query ServiceDependencies {
  apps: apps_v1 {
    name
    dependencies {
      name
    }
    codeComponents {
      url
    }
    jenkinsConfigs {
      instance {
        name
      }
    }
    saasFiles {
      pipelinesProvider {
        provider
      }
      resourceTemplates {
        targets {
          upstream {
            instance {
              name
            }
          }
        }
      }
    }
    quayRepos {
      org {
        name
        instance {
          name
        }
      }
    }
    namespaces {
      managedExternalResources
      externalResources {
        provider
      }
      kafkaCluster {
        name
      }
    }
  }
}

"""


class DependencyV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppCodeComponentsV1(BaseModel):
    url: str = Field(..., alias="url")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsInstanceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsConfigV1(BaseModel):
    instance: JenkinsInstanceV1 = Field(..., alias="instance")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetUpstreamV1_JenkinsInstanceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetUpstreamV1(BaseModel):
    instance: SaasResourceTemplateTargetUpstreamV1_JenkinsInstanceV1 = Field(
        ..., alias="instance"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateTargetV2(BaseModel):
    upstream: Optional[SaasResourceTemplateTargetUpstreamV1] = Field(
        ..., alias="upstream"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasResourceTemplateV2(BaseModel):
    targets: Optional[list[SaasResourceTemplateTargetV2]] = Field(..., alias="targets")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2(BaseModel):
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")
    resource_templates: Optional[list[SaasResourceTemplateV2]] = Field(
        ..., alias="resourceTemplates"
    )

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


class AppQuayReposV1(BaseModel):
    org: QuayOrgV1 = Field(..., alias="org")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceExternalResourceV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class KafkaClusterV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    managed_external_resources: Optional[bool] = Field(
        ..., alias="managedExternalResources"
    )
    external_resources: Optional[list[NamespaceExternalResourceV1]] = Field(
        ..., alias="externalResources"
    )
    kafka_cluster: Optional[KafkaClusterV1] = Field(..., alias="kafkaCluster")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    name: str = Field(..., alias="name")
    dependencies: Optional[list[DependencyV1]] = Field(..., alias="dependencies")
    code_components: Optional[list[AppCodeComponentsV1]] = Field(
        ..., alias="codeComponents"
    )
    jenkins_configs: Optional[list[JenkinsConfigV1]] = Field(
        ..., alias="jenkinsConfigs"
    )
    saas_files: Optional[list[SaasFileV2]] = Field(..., alias="saasFiles")
    quay_repos: Optional[list[AppQuayReposV1]] = Field(..., alias="quayRepos")
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ServiceDependenciesQueryData(BaseModel):
    apps: Optional[list[AppV1]] = Field(..., alias="apps")

    class Config:
        smart_union = True
        extra = Extra.forbid
