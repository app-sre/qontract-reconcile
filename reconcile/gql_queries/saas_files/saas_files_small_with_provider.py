"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SaasFileV2(BaseModel):
    name: str = Field(..., alias="name")
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    saas_files: Optional[list[SaasFileV2]] = Field(..., alias="saasFiles")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ListSaasFilesV2SmallQuery(BaseModel):
    apps_v1: Optional[list[AppV1]] = Field(..., alias="apps_v1")

    class Config:
        smart_union = True
        extra = Extra.forbid
