from pydantic import BaseModel

from reconcile.gql_definitions.cost_report.cost_namespaces import query
from reconcile.utils.gql import GqlApi


class CostNamespace(BaseModel):
    name: str
    app_name: str
    cluster_name: str
    cluster_external_id: str | None

    class Config:
        frozen = True


def get_cost_namespaces(
    gql_api: GqlApi,
) -> list[CostNamespace]:
    namespaces = query(gql_api.query).namespaces or []
    return [
        CostNamespace(
            name=namespace.name,
            app_name=namespace.app.name,
            cluster_name=namespace.cluster.name,
            cluster_external_id=namespace.cluster.spec.external_id,
        )
        for namespace in namespaces
    ]
