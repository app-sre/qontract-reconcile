from reconcile.gql_definitions.common.namespaces_minimal import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql


def get_namespaces_minimal() -> list[NamespaceV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.namespaces or [])
