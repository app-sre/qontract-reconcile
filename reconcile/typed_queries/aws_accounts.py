from typing import Optional

from reconcile.gql_definitions.aws_accounts.aws_accounts import (
    AWSAccountV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_aws_accounts(
    gql_api: GqlApi,
    name: Optional[str] = None,
    uid: Optional[str] = None,
    ecrs: bool = True,
    reset_passwords: bool = False,
    sharing: bool = False,
    terraform_state: bool = False,
) -> list[AWSAccountV1]:
    variables = {
        "name": name,
        "uid": uid,
        "ecrs": ecrs,
        "reset_passwords": reset_passwords,
        "sharing": sharing,
        "terraform_state": terraform_state,
    }
    data = query(gql_api.query, variables=variables)
    return data.accounts or []
