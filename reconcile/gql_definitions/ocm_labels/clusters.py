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

from reconcile.gql_definitions.fragments.ocm_environment import OCMEnvironment


DEFINITION = """
fragment OCMEnvironment on OpenShiftClusterManagerEnvironment_v1 {
    name
    url
    accessTokenClientId
    accessTokenUrl
    accessTokenClientSecret {
        ... VaultSecret
    }
}

fragment VaultSecret on VaultSecret_v1 {
    path
    field
    version
    format
}

query OcmSubscriptionLabel {
  clusters: clusters_v1 {
    name
    spec {
      id
    }
    ocm {
      environment {
        ...OCMEnvironment
      }
      orgId

    }
    disable {
      integrations
    }
    ocmSubscriptionLabels
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union=True
        extra=Extra.forbid


class ClusterSpecV1(ConfiguredBaseModel):
    q_id: Optional[str] = Field(..., alias="id")


class OpenShiftClusterManagerV1(ConfiguredBaseModel):
    environment: OCMEnvironment = Field(..., alias="environment")
    org_id: str = Field(..., alias="orgId")


class DisableClusterAutomationsV1(ConfiguredBaseModel):
    integrations: Optional[list[str]] = Field(..., alias="integrations")


class ClusterV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    spec: Optional[ClusterSpecV1] = Field(..., alias="spec")
    ocm: Optional[OpenShiftClusterManagerV1] = Field(..., alias="ocm")
    disable: Optional[DisableClusterAutomationsV1] = Field(..., alias="disable")
    ocm_subscription_labels: Optional[Json] = Field(..., alias="ocmSubscriptionLabels")


class OcmSubscriptionLabelQueryData(ConfiguredBaseModel):
    clusters: Optional[list[ClusterV1]] = Field(..., alias="clusters")


def query(query_func: Callable, **kwargs: Any) -> OcmSubscriptionLabelQueryData:
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
        OcmSubscriptionLabelQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return OcmSubscriptionLabelQueryData(**raw_data)
