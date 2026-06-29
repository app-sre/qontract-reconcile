from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.aws_cloudwatch_log_retention.aws_accounts import (
    AWSAccountV1,
    query,
)

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_aws_accounts(
    gql_api: GqlApi,
) -> list[AWSAccountV1]:
    data = query(query_func=gql_api.query)
    return data.accounts or []
