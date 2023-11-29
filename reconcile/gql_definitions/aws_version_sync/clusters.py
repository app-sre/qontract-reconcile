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

query AwsExporterCluster {
  clusters: clusters_v1 {
    name
    prometheusUrl
    automationToken {
      ... VaultSecret
    }
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


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    prometheus_url: str = Field(..., alias="prometheusUrl")
    automation_token: Optional[VaultSecret] = Field(..., alias="automationToken")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")


class AwsExporterClusterQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> AwsExporterClusterQueryData:
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
        AwsExporterClusterQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return AwsExporterClusterQueryData(**raw_data)
