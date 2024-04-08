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


class PrometheusInstanceAuthV1(ConfiguredBaseModel):
    provider: str = Field(..., alias="provider")


class PrometheusInstanceBearerAuthV1(PrometheusInstanceAuthV1):
    token: VaultSecret = Field(..., alias="token")


class PrometheusInstanceOidcAuthV1(PrometheusInstanceAuthV1):
    access_token_client_id: str = Field(..., alias="accessTokenClientId")
    access_token_url: str = Field(..., alias="accessTokenUrl")
    access_token_client_secret: VaultSecret = Field(..., alias="accessTokenClientSecret")


class PrometheusInstance(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    description: Optional[str] = Field(..., alias="description")
    base_url: str = Field(..., alias="baseUrl")
    query_path: Optional[str] = Field(..., alias="queryPath")
    auth: Union[PrometheusInstanceOidcAuthV1, PrometheusInstanceBearerAuthV1, PrometheusInstanceAuthV1] = Field(..., alias="auth")
