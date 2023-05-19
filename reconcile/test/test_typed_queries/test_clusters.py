from collections.abc import (
    Callable,
    Mapping,
)
from typing import Optional

from reconcile.gql_definitions.common.clusters import (
    DEFINITION,
    ClustersQueryData,
)
from reconcile.typed_queries.clusters import get_clusters
from reconcile.utils.gql import GqlApi


def test_no_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(ClustersQueryData, {})
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters(gql_api=api)
    assert len(clusters) == 0
    api.query.assert_called_once_with(DEFINITION, {})


def test_get_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(
        ClustersQueryData,
        {"clusters": [{"name": "a", "auth": []}, {"name": "b", "auth": []}]},
    )
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters(gql_api=api)
    assert len(clusters) == 2
    api.query.assert_called_once_with(DEFINITION, {})


def test_get_clusters_with_name(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(
        ClustersQueryData,
        {},
    )
    api = gql_api_builder(data.dict(by_alias=True))
    get_clusters(gql_api=api, name="test")
    api.query.assert_called_once_with(DEFINITION, {"name": "test"})
