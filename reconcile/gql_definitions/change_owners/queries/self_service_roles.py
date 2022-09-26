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


DEFINITION = """
query SelfServiceRolesQuery {
  roles: roles_v1 {
    name
    path
    self_service {
      change_type {
        name
      }
      datafiles {
        datafileSchema: schema
        path
      }
      resources
    }
    users {
      org_username
      tag_on_merge_requests
    }
    bots {
      org_username
    }
  }
}
"""


class ChangeTypeV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class DatafileObjectV1(BaseModel):
    datafile_schema: str = Field(..., alias="datafileSchema")
    path: str = Field(..., alias="path")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SelfServiceConfigV1(BaseModel):
    change_type: ChangeTypeV1 = Field(..., alias="change_type")
    datafiles: Optional[list[DatafileObjectV1]] = Field(..., alias="datafiles")
    resources: Optional[list[str]] = Field(..., alias="resources")

    class Config:
        smart_union = True
        extra = Extra.forbid


class UserV1(BaseModel):
    org_username: str = Field(..., alias="org_username")
    tag_on_merge_requests: Optional[bool] = Field(..., alias="tag_on_merge_requests")

    class Config:
        smart_union = True
        extra = Extra.forbid


class BotV1(BaseModel):
    org_username: Optional[str] = Field(..., alias="org_username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class RoleV1(BaseModel):
    name: str = Field(..., alias="name")
    path: str = Field(..., alias="path")
    self_service: Optional[list[SelfServiceConfigV1]] = Field(..., alias="self_service")
    users: list[UserV1] = Field(..., alias="users")
    bots: list[BotV1] = Field(..., alias="bots")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SelfServiceRolesQueryQueryData(BaseModel):
    roles: Optional[list[RoleV1]] = Field(..., alias="roles")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> SelfServiceRolesQueryQueryData:
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
        SelfServiceRolesQueryQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return SelfServiceRolesQueryQueryData(**raw_data)
