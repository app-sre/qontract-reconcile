"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from enum import Enum  # noqa: F401 # pylint: disable=W0611
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


DEFINITION = """
query JenkinsConfigs {
  jenkins_configs: jenkins_configs_v1 {
    name
    ...on JenkinsConfig_v1 {
      instance {
        name
        serverUrl
        token {
          path
          field
          version
          format
        }
        deleteMethod
      }
      type
      config
      config_path {
        content
      }
    }
  }
}
"""


class JenkinsConfigV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    q_format: Optional[str] = Field(..., alias="format")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsInstanceV1(BaseModel):
    name: str = Field(..., alias="name")
    server_url: str = Field(..., alias="serverUrl")
    token: VaultSecretV1 = Field(..., alias="token")
    delete_method: Optional[str] = Field(..., alias="deleteMethod")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ResourceV1(BaseModel):
    content: str = Field(..., alias="content")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsConfigV1_JenkinsConfigV1(JenkinsConfigV1):
    instance: JenkinsInstanceV1 = Field(..., alias="instance")
    q_type: str = Field(..., alias="type")
    config: Optional[Json] = Field(..., alias="config")
    config_path: Optional[ResourceV1] = Field(..., alias="config_path")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JenkinsConfigsQueryData(BaseModel):
    jenkins_configs: Optional[
        list[Union[JenkinsConfigV1_JenkinsConfigV1, JenkinsConfigV1]]
    ] = Field(..., alias="jenkins_configs")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> JenkinsConfigsQueryData:
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
        JenkinsConfigsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return JenkinsConfigsQueryData(**raw_data)
