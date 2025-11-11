from collections.abc import (
    Callable,
    Mapping,
)
from typing import TYPE_CHECKING, cast

from reconcile.gql_definitions.common.clusters import (
    DEFINITION,
    ClustersQueryData,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.gql import GqlApi

if TYPE_CHECKING:
    from unittest.mock import MagicMock


def test_no_clusters(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(ClustersQueryData, {})
    api = gql_api_builder(data.model_dump(by_alias=True))
    clusters = get_clusters(gql_api=api)
    assert len(clusters) == 0
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION, {})


def test_get_clusters(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(
        ClustersQueryData,
        {"clusters": [{"name": "a", "auth": []}, {"name": "b", "auth": []}]},
    )
    api = gql_api_builder(data.model_dump(by_alias=True))
    clusters = get_clusters(gql_api=api)
    assert len(clusters) == 2
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION, {})


def test_get_clusters_with_name(
    gql_api_builder: Callable[[Mapping | None], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(
        ClustersQueryData,
        {},
    )
    api = gql_api_builder(data.model_dump(by_alias=True))
    get_clusters(gql_api=api, name="test")
    cast("MagicMock", api).query.assert_called_once_with(DEFINITION, {"name": "test"})
