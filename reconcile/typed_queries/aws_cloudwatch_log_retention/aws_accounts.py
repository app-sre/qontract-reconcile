from reconcile.gql_definitions.aws_cloudwatch_log_retention.aws_accounts import (
    AWSAccountV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_aws_accounts(
    gql_api: GqlApi,
) -> list[AWSAccountV1]:
    data = query(query_func=gql_api.query)
    return data.accounts or []
