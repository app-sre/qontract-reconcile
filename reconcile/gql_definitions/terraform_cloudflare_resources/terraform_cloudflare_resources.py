"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from enum import Enum  # noqa: F401 # pylint: disable=W0611
from typing import (  # noqa: F401 # pylint: disable=W0611
    Any,
    Callable,
    Optional,
    Union,
)

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


DEFINITION = """
query TerraformCloudflareResources {
  namespaces: namespaces_v1 {
    name
    managedExternalResources
    externalResources {
      ... on NamespaceTerraformProviderResourceCloudflare_v1 {
        provider
        provisioner {
          name
        }
        resources {
          provider
          ... on NamespaceTerraformResourceCloudflareWorkerScript_v1
          {
            identifier
            name
            content_from_github {
              repo
              path
              ref
            }
            vars {
              name
              text
            }
          }
          ... on NamespaceTerraformResourceCloudflareZone_v1
          {
            identifier
            zone
            plan
            type
            settings
            argo {
              smart_routing
              tiered_caching
            }
            records {
              name
              type
              ttl
              value
              proxied
            }
            workers {
              identifier
              pattern
              script_name
            }
            certificates {
              identifier
              type
              hosts
              validation_method
              validity_days
              certificate_authority
              cloudflare_branding
              wait_for_active_status
            }
          }
        }
      }
    }
  }
}
"""


class NamespaceExternalResourceV1(BaseModel):
    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareAccountV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformResourceCloudflareV1(BaseModel):
    provider: str = Field(..., alias="provider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneWorkerScriptContentFromGithubV1(BaseModel):
    repo: str = Field(..., alias="repo")
    path: str = Field(..., alias="path")
    ref: str = Field(..., alias="ref")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneWorkerScriptVarsV1(BaseModel):
    name: str = Field(..., alias="name")
    text: str = Field(..., alias="text")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformResourceCloudflareWorkerScriptV1(
    NamespaceTerraformResourceCloudflareV1
):
    identifier: str = Field(..., alias="identifier")
    name: str = Field(..., alias="name")
    content_from_github: Optional[
        CloudflareZoneWorkerScriptContentFromGithubV1
    ] = Field(..., alias="content_from_github")
    vars: Optional[list[CloudflareZoneWorkerScriptVarsV1]] = Field(..., alias="vars")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneArgoV1(BaseModel):
    smart_routing: Optional[bool] = Field(..., alias="smart_routing")
    tiered_caching: Optional[bool] = Field(..., alias="tiered_caching")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneRecordV1(BaseModel):
    name: str = Field(..., alias="name")
    q_type: str = Field(..., alias="type")
    ttl: int = Field(..., alias="ttl")
    value: str = Field(..., alias="value")
    proxied: Optional[bool] = Field(..., alias="proxied")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneWorkerV1(BaseModel):
    identifier: str = Field(..., alias="identifier")
    pattern: str = Field(..., alias="pattern")
    script_name: str = Field(..., alias="script_name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CloudflareZoneCertificateV1(BaseModel):
    identifier: str = Field(..., alias="identifier")
    q_type: str = Field(..., alias="type")
    hosts: list[str] = Field(..., alias="hosts")
    validation_method: str = Field(..., alias="validation_method")
    validity_days: int = Field(..., alias="validity_days")
    certificate_authority: str = Field(..., alias="certificate_authority")
    cloudflare_branding: Optional[bool] = Field(..., alias="cloudflare_branding")
    wait_for_active_status: Optional[bool] = Field(..., alias="wait_for_active_status")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformResourceCloudflareZoneV1(
    NamespaceTerraformResourceCloudflareV1
):
    identifier: str = Field(..., alias="identifier")
    zone: str = Field(..., alias="zone")
    plan: Optional[str] = Field(..., alias="plan")
    q_type: Optional[str] = Field(..., alias="type")
    settings: Optional[Json] = Field(..., alias="settings")
    argo: Optional[CloudflareZoneArgoV1] = Field(..., alias="argo")
    records: Optional[list[CloudflareZoneRecordV1]] = Field(..., alias="records")
    workers: Optional[list[CloudflareZoneWorkerV1]] = Field(..., alias="workers")
    certificates: Optional[list[CloudflareZoneCertificateV1]] = Field(
        ..., alias="certificates"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceTerraformProviderResourceCloudflareV1(NamespaceExternalResourceV1):
    provider: str = Field(..., alias="provider")
    provisioner: CloudflareAccountV1 = Field(..., alias="provisioner")
    resources: list[
        Union[
            NamespaceTerraformResourceCloudflareZoneV1,
            NamespaceTerraformResourceCloudflareWorkerScriptV1,
            NamespaceTerraformResourceCloudflareV1,
        ]
    ] = Field(..., alias="resources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")
    managed_external_resources: Optional[bool] = Field(
        ..., alias="managedExternalResources"
    )
    external_resources: Optional[
        list[
            Union[
                NamespaceTerraformProviderResourceCloudflareV1,
                NamespaceExternalResourceV1,
            ]
        ]
    ] = Field(..., alias="externalResources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class TerraformCloudflareResourcesQueryData(BaseModel):
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs: Any) -> TerraformCloudflareResourcesQueryData:
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
        TerraformCloudflareResourcesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return TerraformCloudflareResourcesQueryData(**raw_data)
