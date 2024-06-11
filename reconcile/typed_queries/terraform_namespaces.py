from collections.abc import Callable

from reconcile.gql_definitions.terraform_resources.terraform_resources_namespaces import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql


def get_namespaces(query_func: Callable | None = None) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    return list(data.namespaces or [])
