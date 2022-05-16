"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Field, Json  # noqa: F401  # pylint: disable=W0611


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = 'forbid'


class SaasFileV2(BaseModel):
    name: str = Field(..., alias="name")
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")

    class Config:
        smart_union = True
        extra = 'forbid'


class AppV1(BaseModel):
    saas_files_v2: Optional[list[SaasFileV2]] = Field(..., alias="saasFilesV2")

    class Config:
        smart_union = True
        extra = 'forbid'


class ListSaasFilesV2SmallQuery(BaseModel):
    apps_v1: Optional[list[AppV1]] = Field(..., alias="apps_v1")

    class Config:
        smart_union = True
        extra = 'forbid'
