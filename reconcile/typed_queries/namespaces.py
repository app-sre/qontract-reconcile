from reconcile.gql_definitions.common.namespaces import (
    NamespaceV1,
    query,
)
from reconcile.utils import gql


def get_namespaces() -> list[NamespaceV1]:
    gqlapi = gql.get_api()
    data = query(gqlapi.query)
    return list(data.namespaces or [])
