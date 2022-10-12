"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
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


class ClusterSpecV1(BaseModel):
    private: bool = Field(..., alias="private")

    class Config:
        smart_union = True
        extra = Extra.forbid


class VpcPeeringsValidatorPeeredCluster(BaseModel):
    name: str = Field(..., alias="name")
    spec: Optional[ClusterSpecV1] = Field(..., alias="spec")
    internal: Optional[bool] = Field(..., alias="internal")

    class Config:
        smart_union = True
        extra = Extra.forbid
