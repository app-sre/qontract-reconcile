from collections.abc import Callable

import pytest

from reconcile.gql_definitions.common.clusters_with_peering import (
    ClusterPeeringV1,
    ClustersWithPeeringQueryData,
)
from reconcile.typed_queries.clusters_with_peering import get_clusters_with_peering
from reconcile.utils.gql import GqlApi


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


def test_get_clusters_with_peering(
    gql_api_builder: Callable[..., GqlApi],
    clusters_with_peering: ClustersWithPeeringQueryData,
) -> None:
    gql_api = gql_api_builder(clusters_with_peering.dict(by_alias=True))

    clusters = get_clusters_with_peering(gql_api)

    assert clusters == clusters_with_peering.clusters


def test_get_clusters_with_peering_when_clusters_without_peering(
    gql_api_builder: Callable[..., GqlApi],
    clusters_without_peering: ClustersWithPeeringQueryData,
) -> None:
    gql_api = gql_api_builder(clusters_without_peering.dict(by_alias=True))

    clusters = get_clusters_with_peering(gql_api)

    assert clusters == []
