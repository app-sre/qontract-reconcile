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


DEFINITION = """
query StatusBoard {
  status_board_v1{
    name
    ocm {
      url
      accessTokenUrl
      accessTokenClientId
      accessTokenClientSecret {
        path
        field
        version
        format
      }

    }
    globalAppSelectors {
      exclude
    }
    products {
      productEnvironment {
        name
       	labels
       	product {
       	  name
       	}
        namespaces {
          app {
            name
            onboardingStatus
          }
        }
      }
      appSelectors {
        exclude
      }
    }
  }
}
"""


class ConfiguredBaseModel(BaseModel):
    class Config:
        smart_union = True
        extra = Extra.forbid


class VaultSecretV1(ConfiguredBaseModel):
    path: str = Field(..., alias="path")
    field: str = Field(..., alias="field")
    version: Optional[int] = Field(..., alias="version")
    q_format: Optional[str] = Field(..., alias="format")


class OpenShiftClusterManagerEnvironmentV1(ConfiguredBaseModel):
    url: str = Field(..., alias="url")
    access_token_url: str = Field(..., alias="accessTokenUrl")
    access_token_client_id: str = Field(..., alias="accessTokenClientId")
    access_token_client_secret: VaultSecretV1 = Field(
        ..., alias="accessTokenClientSecret"
    )


class StatusBoardAppSelectorV1(ConfiguredBaseModel):
    exclude: Optional[list[str]] = Field(..., alias="exclude")


class ProductV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")


class AppV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    onboarding_status: str = Field(..., alias="onboardingStatus")


class NamespaceV1(ConfiguredBaseModel):
    app: AppV1 = Field(..., alias="app")


class EnvironmentV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    labels: Optional[Json] = Field(..., alias="labels")
    product: ProductV1 = Field(..., alias="product")
    namespaces: Optional[list[NamespaceV1]] = Field(..., alias="namespaces")


class StatusBoardProductV1_StatusBoardAppSelectorV1(ConfiguredBaseModel):
    exclude: Optional[list[str]] = Field(..., alias="exclude")


class StatusBoardProductV1(ConfiguredBaseModel):
    product_environment: EnvironmentV1 = Field(..., alias="productEnvironment")
    app_selectors: Optional[StatusBoardProductV1_StatusBoardAppSelectorV1] = Field(
        ..., alias="appSelectors"
    )


class StatusBoardV1(ConfiguredBaseModel):
    name: str = Field(..., alias="name")
    ocm: OpenShiftClusterManagerEnvironmentV1 = Field(..., alias="ocm")
    global_app_selectors: Optional[StatusBoardAppSelectorV1] = Field(
        ..., alias="globalAppSelectors"
    )
    products: list[StatusBoardProductV1] = Field(..., alias="products")


class StatusBoardQueryData(ConfiguredBaseModel):
    status_board_v1: Optional[list[StatusBoardV1]] = Field(..., alias="status_board_v1")


def query(query_func: Callable, **kwargs: Any) -> StatusBoardQueryData:
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
        StatusBoardQueryData: queried data parsed into generated classes
    """
    raw_data: dict[Any, Any] = query_func(DEFINITION, **kwargs)
    return StatusBoardQueryData(**raw_data)
