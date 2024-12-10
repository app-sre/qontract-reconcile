from reconcile.gql_definitions.common.aws_vpc_requests import VPCRequest, query
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_aws_vpc_requests(gql_api: GqlApi | None = None) -> list[VPCRequest]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return list(data.vpc_requests or [])
