from collections.abc import (
    Callable,
    Mapping,
)
from typing import Optional

from reconcile.gql_definitions.common.clusters_with_dms import (
    DEFINITION,
    ClustersWithMonitoringQueryData,
)
from reconcile.typed_queries.clusters_with_dms import (
    get_clusters_with_dms,
)
from reconcile.utils.gql import GqlApi


def test_no_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersWithMonitoringQueryData],
) -> None:
    data = gql_class_factory(ClustersWithMonitoringQueryData, [])
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters_with_dms(gql_api=api)
    assert len(clusters) == 0
    api.query.assert_called_once_with(
        DEFINITION, {"filter": {"enableDeadMansSnitch": {"ne": None}}}
    )


def test_get_clusters(
    gql_api_builder: Callable[[Optional[Mapping]], GqlApi],
    gql_class_factory: Callable[..., ClustersWithMonitoringQueryData],
) -> None:
    data = gql_class_factory(
        ClustersWithMonitoringQueryData,
        {
            "clusters": [
                {
                    "name": "test_cluster",
                    "alertmanagerUrl": "something1.devshift.net",
                    "enableDeadMansSnitch": True,
                }
            ]
        },
    )
    api = gql_api_builder(data.dict(by_alias=True))
    clusters = get_clusters_with_dms(gql_api=api)
    assert len(clusters) == 1
    api.query.assert_called_once_with(
        DEFINITION, {"filter": {"enableDeadMansSnitch": {"ne": None}}}
    )
