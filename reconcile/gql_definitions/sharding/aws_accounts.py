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


DEFINITION = """
query AWSAccountSharding {
    aws_accounts: awsaccounts_v1 {
        name
        disable {
            integrations
        }
    }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union = True
        extra = Extra.forbid


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")


class AWSAccountShardingQueryData(ConfiguredBaseModel):
    aws_accounts: Optional[list[AWSAccountV1]] = Field(..., alias="aws_accounts")


def query(query_func: Callable, **kwargs: Any) -> AWSAccountShardingQueryData:
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
        AWSAccountShardingQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return AWSAccountShardingQueryData(**raw_data)
