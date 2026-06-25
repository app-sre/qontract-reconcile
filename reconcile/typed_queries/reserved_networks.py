from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.reserved_networks import (
    NetworkV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_networks(gql_api: GqlApi | None = None) -> list[NetworkV1]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return list(data.networks or [])
