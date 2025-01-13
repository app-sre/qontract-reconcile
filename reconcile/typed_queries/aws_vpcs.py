from reconcile.gql_definitions.common.aws_vpcs import (
    AWSVPC,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_aws_vpcs(gql_api: GqlApi | None = None) -> list[AWSVPC]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return list(data.vpcs or [])
