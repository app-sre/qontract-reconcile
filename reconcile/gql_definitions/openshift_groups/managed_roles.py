"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from collections.abc import Callable  # noqa: F401 # pylint: disable=W0611
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

from reconcile.gql_definitions.fragments.user import User


DEFINITION = """
fragment User on User_v1 {
  name
  org_username
  github_username
  slack_username
  pagerduty_username
}

query OpenshiftGroupsManagedRoles {
  roles: roles_v1 {
    name
    users {
      ... User
    }
    expirationDate
    access {
      cluster {
        name
        auth {
          service
        }
      }
      group
    }
  }
}
"""


class ClusterAuthV1(BaseModel):
    service: str = Field(..., alias="service")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")
    auth: list[ClusterAuthV1] = Field(..., alias="auth")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AccessV1(BaseModel):
    cluster: Optional[ClusterV1] = Field(..., alias="cluster")
    group: Optional[str] = Field(..., alias="group")

    class Config:
        smart_union = True
        extra = Extra.forbid


class RoleV1(BaseModel):
    name: str = Field(..., alias="name")
    users: list[User] = Field(..., alias="users")
    expiration_date: Optional[str] = Field(..., alias="expirationDate")
    access: Optional[list[AccessV1]] = Field(..., alias="access")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OpenshiftGroupsManagedRolesQueryData(BaseModel):
    roles: Optional[list[RoleV1]] = Field(..., alias="roles")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs: Any) -> OpenshiftGroupsManagedRolesQueryData:
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
        OpenshiftGroupsManagedRolesQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return OpenshiftGroupsManagedRolesQueryData(**raw_data)
