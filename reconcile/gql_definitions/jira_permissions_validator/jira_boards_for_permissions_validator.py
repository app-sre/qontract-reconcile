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

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query JiraBoardsForPermissionValidation {
  jira_boards: jira_boards_v1 {
    path
    name
    server {
      serverUrl
      token {
        ... VaultSecret
      }
    }
    issueType
    issueResolveState
    issueReopenState
    issueSecurityId
    severityPriorityMappings {
      name
      mappings {
        priority
      }
    }
    escalationPolicies {
      name
      channels {
        jiraComponent
      }
    }
    disable {
      integrations
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class JiraServerV1(ConfiguredBaseModel):
    server_url: str = Field(..., alias="serverUrl")
    token: VaultSecret = Field(..., alias="token")


class SeverityPriorityMappingV1(ConfiguredBaseModel):
    priority: str = Field(..., alias="priority")


class JiraSeverityPriorityMappingsV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    mappings: list[SeverityPriorityMappingV1] = Field(..., alias="mappings")


class AppEscalationPolicyChannelsV1(ConfiguredBaseModel):
    jira_component: Optional[str] = Field(..., alias="jiraComponent")


class AppEscalationPolicyV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    channels: AppEscalationPolicyChannelsV1 = Field(..., alias="channels")


class DisableJiraBoardAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class JiraBoardV1(ConfiguredBaseModel):
    path: str = Field(..., alias="path")
    name: str = Field(..., alias="name")
    server: JiraServerV1 = Field(..., alias="server")
    issue_type: Optional[str] = Field(..., alias="issueType")
    issue_resolve_state: Optional[str] = Field(..., alias="issueResolveState")
    issue_reopen_state: Optional[str] = Field(..., alias="issueReopenState")
    issue_security_id: Optional[str] = Field(..., alias="issueSecurityId")
    severity_priority_mappings: JiraSeverityPriorityMappingsV1 = Field(..., alias="severityPriorityMappings")
    escalation_policies: Optional[list[AppEscalationPolicyV1]] = Field(..., alias="escalationPolicies")
    disable: Optional[DisableJiraBoardAutomationsV1] = Field(..., alias="disable")


class JiraBoardsForPermissionValidationQueryData(ConfiguredBaseModel):
    jira_boards: Optional[list[JiraBoardV1]] = Field(..., alias="jira_boards")


def query(query_func: Callable, **kwargs: Any) -> JiraBoardsForPermissionValidationQueryData:
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
        JiraBoardsForPermissionValidationQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return JiraBoardsForPermissionValidationQueryData(**raw_data)
