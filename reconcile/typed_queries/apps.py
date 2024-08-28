from collections.abc import Callable

from reconcile.gql_definitions.common.apps import AppV1, query
from reconcile.utils import gql


def get_apps(query_func: Callable | None = None) -> list[AppV1]:
    if not query_func:
        gqlapi = gql.get_api()
        query_func = gqlapi.query
    return query(query_func=query_func).apps or []
