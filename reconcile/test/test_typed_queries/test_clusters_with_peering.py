from collections.abc import Callable

import pytest
from pytest_mock import MockerFixture

from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterPeeringV1,
    ClustersWithPeeringQueryData,
)
from reconcile.typed_queries.clusters_with_peering import get_clusters_with_peering


@pytest.fixture
def peering(
    gql_class_factory: Callable[..., ClusterPeeringV1],
) -> ClusterPeeringV1:
    return gql_class_factory(
        ClusterPeeringV1,
        {"connections": []},
    )


@pytest.fixture
def clusters_with_peering(
    gql_class_factory: Callable[..., ClustersWithPeeringQueryData],
    peering,
) -> ClustersWithPeeringQueryData:
    return gql_class_factory(
        ClustersWithPeeringQueryData,
        {
            "clusters": [
                {"peering": peering.dict(by_alias=True)},
            ]
        },
    )


@pytest.fixture
def clusters_without_peering(
    gql_class_factory: Callable[..., ClustersWithPeeringQueryData],
) -> ClustersWithPeeringQueryData:
    return gql_class_factory(
        ClustersWithPeeringQueryData,
        {
            "clusters": [
                {"peering": None},
            ]
        },
    )


def _setup_gql_query_data(
    data: ClustersWithPeeringQueryData,
    mocker: MockerFixture,
    query_func: Callable[..., Callable],
) -> None:
    mocker.patch(
        "reconcile.typed_queries.clusters_with_peering.gql"
    ).get_query_func.return_value = query_func(data.dict(by_alias=True))


def test_get_clusters_with_peering(
    mocker: MockerFixture,
    query_func: Callable[..., Callable],
    clusters_with_peering: ClustersWithPeeringQueryData,
) -> None:
    _setup_gql_query_data(clusters_with_peering, mocker, query_func)

    clusters = get_clusters_with_peering()

    assert clusters == clusters_with_peering.clusters


def test_get_clusters_with_peering_when_clusters_without_peering(
    mocker: MockerFixture,
    query_func: Callable[..., Callable],
    clusters_without_peering: ClustersWithPeeringQueryData,
) -> None:
    _setup_gql_query_data(clusters_without_peering, mocker, query_func)

    clusters = get_clusters_with_peering()

    assert clusters == []
