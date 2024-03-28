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


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class AWSTerraformStateIntegrationsV1(ConfiguredBaseModel):
    integration: str = Field(..., alias="integration")
    key: str = Field(..., alias="key")


class TerraformStateAWSV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")
    bucket: str = Field(..., alias="bucket")
    region: str = Field(..., alias="region")
    integrations: list[AWSTerraformStateIntegrationsV1] = Field(..., alias="integrations")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    uid: str = Field(..., alias="uid")
    terraform_username: Optional[str] = Field(..., alias="terraformUsername")
    automation_token: VaultSecret = Field(..., alias="automationToken")
    supported_deployment_regions: Optional[list[str]] = Field(..., alias="supportedDeploymentRegions")
    resources_default_region: str = Field(..., alias="resourcesDefaultRegion")
    provider_version: str = Field(..., alias="providerVersion")
    terraform_state: Optional[TerraformStateAWSV1] = Field(..., alias="terraformState")


class NetworkV1(ConfiguredBaseModel):
    network_address: str = Field(..., alias="networkAddress")


class VPCRequestSubnetsV1(ConfiguredBaseModel):
    private: Optional[list[str]] = Field(..., alias="private")
    public: Optional[list[str]] = Field(..., alias="public")


class VPCRequest(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    account: AWSAccountV1 = Field(..., alias="account")
    region: str = Field(..., alias="region")
    cidr_block: NetworkV1 = Field(..., alias="cidr_block")
    subnets: Optional[VPCRequestSubnetsV1] = Field(..., alias="subnets")
