from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.users_with_paths import UserV1, query
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Callable


def get_users_with_paths(query_func: Callable | None = None) -> list[UserV1]:
    if not query_func:
        query_func = gql.get_api().query
    return query(query_func=query_func).users or []
