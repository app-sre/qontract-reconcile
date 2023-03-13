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
    def cluster(self) -> Cluster:
        ...


NS = TypeVar("NS", bound=Namespace)


def filter_namespaces_by_cluster(
    namespaces: Iterable[NS], cluster_name: str
) -> list[NS]:
    return [n for n in namespaces if n.cluster.name == cluster_name]


def filter_namespaces_by_name(
    namespaces: Iterable[NS], namespace_name: str
) -> list[NS]:
    return [n for n in namespaces if n.name == namespace_name]


def filter_namespaces_by_cluster_and_namespace(
    namespaces: Iterable[NS],
    cluster_name: Optional[str],
    namespace_name: Optional[str],
) -> list[NS]:
    """
    Filter namespaces by cluster and namespace name.
    Cluster name takes precedence over namespace name, i.e.,
    if the cluster name does not exist then the result will
    be empty, no matter if the namespace name exists or not.
    """
    result: list[NS] = list(namespaces)
    if cluster_name:
        result = filter_namespaces_by_cluster(
            namespaces=result, cluster_name=cluster_name
        )
    if namespace_name:
        result = filter_namespaces_by_name(
            namespaces=result, namespace_name=namespace_name
        )
    return result
