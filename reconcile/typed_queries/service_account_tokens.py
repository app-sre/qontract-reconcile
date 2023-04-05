from collections.abc import Callable
from typing import Optional

from reconcile.gql_definitions.service_account_tokens.service_account_tokens import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql


def get_namespaces_with_service_account_tokens(
    query_func: Optional[Callable] = None,
) -> list[NamespaceV1]:
    if not query_func:
        query_func = gql.get_api().query
    namespaces = query(query_func).namespaces or []
    return namespaces
