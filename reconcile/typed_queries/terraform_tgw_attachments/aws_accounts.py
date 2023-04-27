from typing import Optional

from reconcile.gql_definitions.terraform_tgw_attachments.aws_accounts import (
    AWSAccountV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_aws_accounts(
    gql_api: GqlApi,
    name: Optional[str] = None,
) -> list[AWSAccountV1]:
    variables = {
        "name": name,
    }
    data = query(gql_api.query, variables=variables)
    return data.accounts or []
