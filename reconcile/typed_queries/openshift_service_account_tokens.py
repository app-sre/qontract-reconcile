from reconcile.gql_definitions.openshift_service_account_tokens.openshift_service_account_tokens import (
    NamespaceV1,
    query,
)
from reconcile.utils.gql import GqlApi


def get_openshift_service_account_tokens(
    gql_api: GqlApi,
) -> list[NamespaceV1]:
    data = query(gql_api.query)
    return data.namespaces or []
