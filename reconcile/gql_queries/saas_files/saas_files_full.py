"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611


class VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    f_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: VaultSecretV1 = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SlackOutputV1(BaseModel):
    channel: Optional[str] = Field(..., alias="channel")
    username: Optional[str] = Field(..., alias="username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2(BaseModel):
    labels: Optional[Json] = Field(..., alias="labels")
    secret_parameters: Optional[list[SaasSecretParametersV1]] = Field(..., alias="secretParameters")
    name: str = Field(..., alias="name")
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")
    slack: Optional[SlackOutputV1] = Field(..., alias="slack")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    saas_files: Optional[list[SaasFileV2]] = Field(..., alias="saasFiles")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFilesV2FullQuery(BaseModel):
    apps_v1: Optional[list[AppV1]] = Field(..., alias="apps_v1")

    class Config:
        smart_union = True
        extra = Extra.forbid
