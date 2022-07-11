"""
Generated by qenerate plugin=pydantic_v1. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import (  # noqa: F401 # pylint: disable=W0611
    BaseModel,
    Extra,
    Field,
    Json,
)


class OwnerV1(BaseModel):
    email: str = Field(..., alias="email")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    service_owners: Optional[list[OwnerV1]] = Field(..., alias="serviceOwners")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ClusterV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AWSAccountV1_OwnerV1(BaseModel):
    email: str = Field(..., alias="email")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AWSAccountV1(BaseModel):
    account_owners: Optional[list[AWSAccountV1_OwnerV1]] = Field(..., alias="accountOwners")

    class Config:
        smart_union = True
        extra = Extra.forbid


class UserV1(BaseModel):
    org_username: str = Field(..., alias="org_username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class RoleV1(BaseModel):
    users: Optional[list[UserV1]] = Field(..., alias="users")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceEmailAudienceV1_UserV1(BaseModel):
    org_username: str = Field(..., alias="org_username")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceEmailAudienceV1(BaseModel):
    aliases: Optional[list[str]] = Field(..., alias="aliases")
    services: Optional[list[AppV1]] = Field(..., alias="services")
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")
    aws_accounts: Optional[list[AWSAccountV1]] = Field(..., alias="aws_accounts")
    roles: Optional[list[RoleV1]] = Field(..., alias="roles")
    users: Optional[list[AppInterfaceEmailAudienceV1_UserV1]] = Field(..., alias="users")

    class Config:
        smart_union = True
        extra = Extra.forbid


class Email(BaseModel):
    name: str = Field(..., alias="name")
    subject: str = Field(..., alias="subject")
    q_to: AppInterfaceEmailAudienceV1 = Field(..., alias="to")
    body: str = Field(..., alias="body")

    class Config:
        smart_union = True
        extra = Extra.forbid
