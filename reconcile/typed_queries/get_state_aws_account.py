from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.common.state_aws_account import (
    AWSAccountV1,
    query,
)
from reconcile.utils import gql

if TYPE_CHECKING:
    from collections.abc import Callable


def get_state_aws_account(
    name: str, query_func: Callable | None = None
) -> AWSAccountV1 | None:
    if not query_func:
        query_func = gql.get_api().query
    if (
        accounts := query(query_func=query_func, variables={"name": name}).accounts
        or []
    ):
        return accounts[0]
    return None
