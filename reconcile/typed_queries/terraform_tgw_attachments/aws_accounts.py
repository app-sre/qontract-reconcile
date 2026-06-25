from __future__ import annotations

from typing import TYPE_CHECKING

from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
    query,
)

if TYPE_CHECKING:
    from reconcile.utils.gql import GqlApi


def get_aws_accounts(
    gql_api: GqlApi,
    name: str | None = None,
) -> list[AWSAccountV1]:
    variables = {
        "name": name,
    }
    data = query(gql_api.query, variables=variables)
    return data.accounts or []
