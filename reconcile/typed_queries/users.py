from collections.abc import Callable

from reconcile.gql_definitions.common.users import query
from reconcile.gql_definitions.fragments.user import User
from reconcile.utils import gql


def get_users(query_func: Callable | None = None) -> list[User]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func=gql.get_api().query).users or []
