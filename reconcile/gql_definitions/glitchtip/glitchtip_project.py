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
query Projects {
  apps: apps_v1 {
    glitchtipProjects {
      name
      platform
      teams {
        name
        roles {
          glitchtip_roles {
            organization {
              name
            }
            role
          }
          users {
            github_username
          }
        }
      }
      organization {
        name
        instance {
          name
        }
      }
    }
  }
}
"""


class GlitchtipOrganizationV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipRoleV1(BaseModel):
    organization: GlitchtipOrganizationV1 = Field(..., alias="organization")
    role: str = Field(..., alias="role")

    class Config:
        smart_union = True
        extra = Extra.forbid


class UserV1(BaseModel):
    github_username: str = Field(..., alias="github_username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class RoleV1(BaseModel):
    glitchtip_roles: Optional[list[GlitchtipRoleV1]] = Field(
        ..., alias="glitchtip_roles"
    )
    users: list[UserV1] = Field(..., alias="users")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipTeamV1(BaseModel):
    name: str = Field(..., alias="name")
    roles: list[RoleV1] = Field(..., alias="roles")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipInstanceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipProjectsV1_GlitchtipOrganizationV1(BaseModel):
    name: str = Field(..., alias="name")
    instance: GlitchtipInstanceV1 = Field(..., alias="instance")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GlitchtipProjectsV1(BaseModel):
    name: str = Field(..., alias="name")
    platform: str = Field(..., alias="platform")
    teams: list[GlitchtipTeamV1] = Field(..., alias="teams")
    organization: GlitchtipProjectsV1_GlitchtipOrganizationV1 = Field(
        ..., alias="organization"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    glitchtip_projects: Optional[list[GlitchtipProjectsV1]] = Field(
        ..., alias="glitchtipProjects"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class ProjectsQueryData(BaseModel):
    apps: Optional[list[AppV1]] = Field(..., alias="apps")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> ProjectsQueryData:
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
        ProjectsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return ProjectsQueryData(**raw_data)
