from typing import Optional

from reconcile.gql_definitions.common.aws_managed_vpcs import AWSManagedVPC, query
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_aws_managed_vpcs(gql_api: Optional[GqlApi] = None) -> list[AWSManagedVPC]:
    api = gql_api if gql_api else gql.get_api()
    data = query(query_func=api.query)
    return list(data.managed_vpcs or [])
