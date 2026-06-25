from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.users import query
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Callable

    from reconcile.gql_definitions.fragments.user import User


def get_users(query_func: Callable | None = None) -> list[User]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func=gql.get_api().query).users or []
