from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.external_resources.external_resources_namespaces import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql


def get_namespaces(query_func: Optional[Callable] = None) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    data = query(query_func=query_func)
    return list(data.namespaces or [])
