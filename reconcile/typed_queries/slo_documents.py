from reconcile.gql_definitions.slo_documents.slo_documents import (
    SLODocumentV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_slo_documents(gql_api: GqlApi | None = None) -> list[SLODocumentV1]:
    api = gql_api or gql.get_api()
    data = query(query_func=api.query)
    return data.slo_document_v1 or []
