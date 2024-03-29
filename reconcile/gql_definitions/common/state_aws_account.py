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
query StateAwsAccount($name: String){
  accounts: awsaccounts_v1 (name: $name)
  {
    name
    resourcesDefaultRegion
    automationToken {
      path
      field
      version
      format
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class VaultSecretV1(ConfiguredBaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    q_format: Optional[str] = Field(..., alias="format")


class AWSAccountV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    resources_default_region: str = Field(..., alias="resourcesDefaultRegion")
    automation_token: VaultSecretV1 = Field(..., alias="automationToken")


class StateAwsAccountQueryData(ConfiguredBaseModel):
    accounts: Optional[list[AWSAccountV1]] = Field(..., alias="accounts")


def query(query_func: Callable, **kwargs: Any) -> StateAwsAccountQueryData:
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
        StateAwsAccountQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return StateAwsAccountQueryData(**raw_data)
