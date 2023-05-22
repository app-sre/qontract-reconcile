from collections.abc import (
    Callable,
    Mapping,
)
from typing import Optional

from reconcile.gql_definitions.common.clusters_minimal import (
    DEFINITION,
    ClustersMinimalQueryData,
)
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal
from reconcile.utils.gql import GqlApi


def test_no_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersMinimalQueryData],
) -> None:
    data = gql_class_factory(ClustersMinimalQueryData, {})
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters_minimal(gql_api=api)
    assert len(clusters) == 0
    api.query.assert_called_once_with(DEFINITION, {})


def test_get_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersMinimalQueryData],
) -> None:
    data = gql_class_factory(
        ClustersMinimalQueryData,
        {"clusters": [{"name": "a", "auth": []}, {"name": "b", "auth": []}]},
    )
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters_minimal(gql_api=api)
    assert len(clusters) == 2
    api.query.assert_called_once_with(DEFINITION, {})


def test_get_clusters_with_name(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersMinimalQueryData],
) -> None:
    data = gql_class_factory(
        ClustersMinimalQueryData,
        {},
    )
    api = gql_api_builder(data.dict(by_alias=True))
    get_clusters_minimal(gql_api=api, name="test")
    api.query.assert_called_once_with(DEFINITION, {"name": "test"})
