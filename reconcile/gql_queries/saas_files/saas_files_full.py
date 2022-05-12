"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""

from typing import Any, Optional  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Field, Json  # noqa: F401  # pylint: disable=W0611


class VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    _format: Optional[str] = Field(..., alias="format")


class SaasSecretParametersV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: VaultSecretV1 = Field(..., alias="secret")


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")


class SlackOutputV1(BaseModel):
    channel: Optional[str] = Field(..., alias="channel")
    username: Optional[str] = Field(..., alias="username")


class SaasFileV2(BaseModel):
    labels: Optional[Json] = Field(..., alias="labels")
    secret_parameters: Optional[list[SaasSecretParametersV1]] = Field(..., alias="secretParameters")
    name: str = Field(..., alias="name")
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")
    slack: Optional[SlackOutputV1] = Field(..., alias="slack")


class AppV1(BaseModel):
    saas_files_v2: Optional[list[SaasFileV2]] = Field(..., alias="saasFilesV2")


def data_to_obj(data: dict[Any, Any]) -> list[AppV1]:
    return [AppV1(**el) for el in data["apps_v1"]]
