from collections.abc import Iterable
from typing import (
    Optional,
    Protocol,
    TypeVar,
)


class Cluster(Protocol):
    name: str


class Namespace(Protocol):
    name: str

    @property
    def cluster(self) -> Cluster: ...


NS = TypeVar("NS", bound=Namespace)


def filter_namespaces_by_cluster(
    namespaces: Iterable[NS], cluster_names: Iterable[str]
) -> list[NS]:
    return [n for n in namespaces if n.cluster.name in cluster_names]


def filter_namespaces_by_name(
    namespaces: Iterable[NS], namespace_names: Iterable[str]
) -> list[NS]:
    return [n for n in namespaces if n.name in namespace_names]


def filter_namespaces_by_cluster_and_namespace(
    namespaces: Iterable[NS],
    cluster_names: Optional[Iterable[str]],
    namespace_names: Optional[Iterable[str]],
) -> list[NS]:
    """
    Filter namespaces by cluster and namespace name.
    Cluster name takes precedence over namespace name, i.e.,
    if the cluster name does not exist then the result will
    be empty, no matter if the namespace name exists or not.
    """
    result: list[NS] = list(namespaces)
    if cluster_names:
        result = filter_namespaces_by_cluster(
            namespaces=result, cluster_names=cluster_names
        )
    if namespace_names:
        result = filter_namespaces_by_name(
            namespaces=result, namespace_names=namespace_names
        )
    return result
