from typing import Optional

from reconcile.gql_definitions.openshift_service_account_tokens.openshift_service_account_tokens import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_openshift_service_account_tokens(
    gql_api: Optional[GqlApi] = None,
) -> list[NamespaceV1]:
    api = gql_api if gql_api else gql.get_api()
    data = query(api.query)
    return data.namespaces or []
