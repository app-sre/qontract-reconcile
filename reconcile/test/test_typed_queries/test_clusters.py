from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.gql_definitions.common.clusters import ClustersQueryData
from reconcile.typed_queries.clusters import get_clusters


def test_no_clusters(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(ClustersQueryData, {})
    clusters = get_clusters(query_func=query_func(data.dict(by_alias=True)))
    assert len(clusters) == 0


def test_get_clusters(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., ClustersQueryData],
) -> None:
    data = gql_class_factory(
        ClustersQueryData,
        {"clusters": [{"name": "a", "auth": []}, {"name": "b", "auth": []}]},
    )
    clusters = get_clusters(query_func=query_func(data.dict(by_alias=True)))
    assert len(clusters) == 2
