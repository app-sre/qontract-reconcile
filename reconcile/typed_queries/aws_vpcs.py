from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.aws_vpcs import (
    AWSVPC,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_aws_vpcs(gql_api: GqlApi | None = None) -> list[AWSVPC]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return list(data.vpcs or [])
