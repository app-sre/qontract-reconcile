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

from reconcile.gql_definitions.fragments.vault_secret import VaultSecret


DEFINITION = """
fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query AppInterfaceSettings {
  settings: app_interface_settings_v1 {
    repoUrl
    vault
    kubeBinary
    mergeRequestGateway
    saasDeployJobTemplate
    hashLength
    smtp {
      mailAddress
      timeout
      credentials {
        ... VaultSecret
      }
    }
    imap {
      timeout
      credentials {
        ... VaultSecret
      }
    }
    githubRepoInvites {
      credentials {
        ... VaultSecret
      }
    }
    ldap {
      serverUrl
      baseDn
    }
    dependencies {
      type
      services {
        name
      }
    }
    credentials {
      name
      secret {
        ... VaultSecret
      }
    }
    sqlQuery {
      imageRepository
      pullSecret {
        path
        version
        labels
        annotations
        type
      }
    }
    alertingServices
    endpointMonitoringBlackboxExporterModules
    jiraWatcher {
      readTimeout
      connectTimeout
    }
  }
}
"""


class SmtpSettingsV1(BaseModel):
    mail_address: str = Field(..., alias="mailAddress")
    timeout: Optional[int] = Field(..., alias="timeout")
    credentials: VaultSecret = Field(..., alias="credentials")

    class Config:
        smart_union = True
        extra = Extra.forbid


class ImapSettingsV1(BaseModel):
    timeout: Optional[int] = Field(..., alias="timeout")
    credentials: VaultSecret = Field(..., alias="credentials")

    class Config:
        smart_union = True
        extra = Extra.forbid


class GithubRepoInvitesV1(BaseModel):
    credentials: VaultSecret = Field(..., alias="credentials")

    class Config:
        smart_union = True
        extra = Extra.forbid


class LdapSettingsV1(BaseModel):
    server_url: str = Field(..., alias="serverUrl")
    base_dn: str = Field(..., alias="baseDn")

    class Config:
        smart_union = True
        extra = Extra.forbid


class DependencyV1(BaseModel):
    name: str = Field(..., alias="name")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceDependencyMappingV1(BaseModel):
    q_type: str = Field(..., alias="type")
    services: list[DependencyV1] = Field(..., alias="services")

    class Config:
        smart_union = True
        extra = Extra.forbid


class CredentialsRequestMapV1(BaseModel):
    name: str = Field(..., alias="name")
    secret: VaultSecret = Field(..., alias="secret")

    class Config:
        smart_union = True
        extra = Extra.forbid


class NamespaceOpenshiftResourceVaultSecretV1(BaseModel):
    path: str = Field(..., alias="path")
    version: int = Field(..., alias="version")
    labels: Optional[Json] = Field(..., alias="labels")
    annotations: Optional[Json] = Field(..., alias="annotations")
    q_type: Optional[str] = Field(..., alias="type")

    class Config:
        smart_union = True
        extra = Extra.forbid


class SqlQuerySettingsV1(BaseModel):
    image_repository: str = Field(..., alias="imageRepository")
    pull_secret: NamespaceOpenshiftResourceVaultSecretV1 = Field(
        ..., alias="pullSecret"
    )

    class Config:
        smart_union = True
        extra = Extra.forbid


class JiraWatcherSettingsV1(BaseModel):
    read_timeout: int = Field(..., alias="readTimeout")
    connect_timeout: int = Field(..., alias="connectTimeout")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceSettingsV1(BaseModel):
    repo_url: str = Field(..., alias="repoUrl")
    vault: bool = Field(..., alias="vault")
    kube_binary: str = Field(..., alias="kubeBinary")
    merge_request_gateway: Optional[str] = Field(..., alias="mergeRequestGateway")
    saas_deploy_job_template: str = Field(..., alias="saasDeployJobTemplate")
    hash_length: int = Field(..., alias="hashLength")
    smtp: Optional[SmtpSettingsV1] = Field(..., alias="smtp")
    imap: Optional[ImapSettingsV1] = Field(..., alias="imap")
    github_repo_invites: Optional[GithubRepoInvitesV1] = Field(
        ..., alias="githubRepoInvites"
    )
    ldap: Optional[LdapSettingsV1] = Field(..., alias="ldap")
    dependencies: Optional[list[AppInterfaceDependencyMappingV1]] = Field(
        ..., alias="dependencies"
    )
    credentials: Optional[list[CredentialsRequestMapV1]] = Field(
        ..., alias="credentials"
    )
    sql_query: Optional[SqlQuerySettingsV1] = Field(..., alias="sqlQuery")
    alerting_services: Optional[list[str]] = Field(..., alias="alertingServices")
    endpoint_monitoring_blackbox_exporter_modules: Optional[list[str]] = Field(
        ..., alias="endpointMonitoringBlackboxExporterModules"
    )
    jira_watcher: Optional[JiraWatcherSettingsV1] = Field(..., alias="jiraWatcher")

    class Config:
        smart_union = True
        extra = Extra.forbid


class AppInterfaceSettingsQueryData(BaseModel):
    settings: Optional[list[AppInterfaceSettingsV1]] = Field(..., alias="settings")

    class Config:
        smart_union = True
        extra = Extra.forbid


def query(query_func: Callable, **kwargs) -> AppInterfaceSettingsQueryData:
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
        AppInterfaceSettingsQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, kwargs)
    return AppInterfaceSettingsQueryData(**raw_data)
