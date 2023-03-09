from collections.abc import Iterable
from dataclasses import dataclass
from typing import Optional

import pytest

from reconcile.utils.oc_filters import filter_namespaces_by_cluster_and_namespace


@dataclass
class Cluster:
    name: str


@dataclass
class Namespace:
    name: str
    cluster: Cluster


@pytest.mark.parametrize(
    "namespaces, cluster_name, namespace_name, expected",
    [
        # Filter single namespace
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
            ],
            "test-cluster",
            "test-namespace",
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
            ],
        ),
        # Filter multiple namespaces
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace-2", cluster=Cluster(name="test-cluster-2")
                ),
            ],
            "test-cluster",
            "test-namespace",
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
            ],
        ),
        # Cluster takes precedence over namespace name
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-2")
                ),
            ],
            "test-cluster-3",
            "test-namespace",
            [],
        ),
        # Filter with Nones -> return input
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-2")
                ),
            ],
            None,
            None,
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-2")
                ),
            ],
        ),
    ],
)
def test_filter_namespaces_by_cluster_and_namespace(
    namespaces: Iterable[Namespace],
    cluster_name: Optional[str],
    namespace_name: Optional[str],
    expected: Iterable[Namespace],
):
    result = filter_namespaces_by_cluster_and_namespace(
        namespaces=namespaces,
        cluster_name=cluster_name,
        namespace_name=namespace_name,
    )

    def _sort(items: Iterable[Namespace]) -> list[Namespace]:
        return sorted(items, key=lambda x: (x.name, x.cluster.name))

    # This line is nice to have for debugging
    sorted_result, sorted_expected = _sort(result), _sort(expected)

    assert sorted_result == sorted_expected
