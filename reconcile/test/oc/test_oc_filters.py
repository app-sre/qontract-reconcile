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
    "namespaces, cluster_names, namespace_names, expected",
    [
        # Filter single namespace
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
            ],
            ("test-cluster",),
            ("test-namespace",),
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
            ("test-cluster",),
            ("test-namespace",),
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
            ("test-cluster-3",),
            ("test-namespace",),
            [],
        ),
        # Filter multiple clusters and multiple namespaces
        (
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace-2", cluster=Cluster(name="test-cluster")
                ),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-2")
                ),
                Namespace(
                    name="test-namespace-2", cluster=Cluster(name="test-cluster-2")
                ),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-3")
                ),
            ],
            ("test-cluster", "test-cluster-2"),
            ("test-namespace", "test-namespace-2"),
            [
                Namespace(name="test-namespace", cluster=Cluster(name="test-cluster")),
                Namespace(
                    name="test-namespace-2", cluster=Cluster(name="test-cluster")
                ),
                Namespace(
                    name="test-namespace", cluster=Cluster(name="test-cluster-2")
                ),
                Namespace(
                    name="test-namespace-2", cluster=Cluster(name="test-cluster-2")
                ),
            ],
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
    cluster_names: Optional[Iterable[str]],
    namespace_names: Optional[Iterable[str]],
    expected: Iterable[Namespace],
) -> None:
    result = filter_namespaces_by_cluster_and_namespace(
        namespaces=namespaces,
        cluster_names=cluster_names,
        namespace_names=namespace_names,
    )

    def _sort(items: Iterable[Namespace]) -> list[Namespace]:
        return sorted(items, key=lambda x: (x.name, x.cluster.name))

    # This line is nice to have for debugging
    sorted_result, sorted_expected = _sort(result), _sort(expected)

    assert sorted_result == sorted_expected
