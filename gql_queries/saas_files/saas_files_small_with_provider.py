"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""

from typing import Any, Optional

from pydantic import BaseModel, Field, Json  # noqa: F401  # pylint: disable=W0611


class PipelinesProviderV1(BaseModel):
    name: str = Field(..., alias="name")


class SaasFileV2(BaseModel):
    name: str = Field(..., alias="name")
    pipelines_provider: PipelinesProviderV1 = Field(..., alias="pipelinesProvider")


class AppV1(BaseModel):
    saas_files_v2: Optional[list[SaasFileV2]] = Field(..., alias="saasFilesV2")


def data_to_obj(data: dict[Any, Any]) -> list[AppV1]:
    return [AppV1(**el) for el in data["apps_v1"]]
