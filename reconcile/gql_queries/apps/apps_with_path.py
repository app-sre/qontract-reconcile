"""
THIS IS AN AUTO-GENERATED FILE. DO NOT MODIFY MANUALLY!
"""
from typing import Optional, Union  # noqa: F401 # pylint: disable=W0611

from pydantic import BaseModel, Extra, Field, Json  # noqa: F401  # pylint: disable=W0611


class GrafanaDashboardUrlsV1(BaseModel):
    url: str = Field(..., alias="url")

    class Config:
        smart_union = True
        extra = Extra.forbid


class OwnerV1(BaseModel):
    name: str = Field(..., alias="name")
    email: str = Field(..., alias="email")

    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JiraServerV1(BaseModel):
    server_url: str = Field(..., alias="serverUrl")
    token: VaultSecretV1 = Field(..., alias="token")

    class Config:
        smart_union = True
        extra = Extra.forbid


class JiraBoardV1(BaseModel):
    name: str = Field(..., alias="name")
    server: JiraServerV1 = Field(..., alias="server")

    class Config:
        smart_union = True
        extra = Extra.forbid


class PermissionSlackUsergroupV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppEscalationPolicyChannelsV1(BaseModel):
    jira_board: Optional[list[JiraBoardV1]] = Field(..., alias="jiraBoard")
    slack_user_group: Optional[list[PermissionSlackUsergroupV1]] = Field(..., alias="slackUserGroup")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppEscalationPolicyV1(BaseModel):
    description: str = Field(..., alias="description")
    channels: AppEscalationPolicyChannelsV1 = Field(..., alias="channels")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppV1(BaseModel):
    labels: Optional[Json] = Field(..., alias="labels")
    name: str = Field(..., alias="name")
    description: str = Field(..., alias="description")
    sops_url: str = Field(..., alias="sopsUrl")
    grafana_urls: Optional[list[GrafanaDashboardUrlsV1]] = Field(..., alias="grafanaUrls")
    architecture_document: str = Field(..., alias="architectureDocument")
    service_owners: Optional[list[OwnerV1]] = Field(..., alias="serviceOwners")
    escalation_policy: AppEscalationPolicyV1 = Field(..., alias="escalationPolicy")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppsWithPathQuery(BaseModel):
    apps_v1: Optional[list[AppV1]] = Field(..., alias="apps")

    class Config:
        smart_union = True
        extra = Extra.forbid
