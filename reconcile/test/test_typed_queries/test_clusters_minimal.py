from collections.abc import (
    Callable,
    Mapping,
)

from reconcile.gql_definitions.common.clusters_minimal import ClustersMinimalQueryData
from reconcile.typed_queries.clusters_minimal import get_clusters_minimal


def test_no_clusters(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., ClustersMinimalQueryData],
) -> None:
    data = gql_class_factory(ClustersMinimalQueryData, {})
    clusters = get_clusters_minimal(query_func=query_func(data.dict(by_alias=True)))
    assert len(clusters) == 0


def test_get_clusters(
    query_func: Callable[[Mapping], Callable],
    gql_class_factory: Callable[..., ClustersMinimalQueryData],
) -> None:
    data = gql_class_factory(
        ClustersMinimalQueryData,
        {"clusters": [{"name": "a", "auth": []}, {"name": "b", "auth": []}]},
    )
    clusters = get_clusters_minimal(query_func=query_func(data.dict(by_alias=True)))
    assert len(clusters) == 2
