from pydantic import BaseModel

from reconcile.gql_definitions.cost_report.cost_namespaces import query
from reconcile.utils.gql import GqlApi


class CostNamespaceLabels(BaseModel, frozen=True):
    insights_cost_management_optimizations: str | None = None


class CostNamespace(BaseModel, frozen=True):
    name: str
    labels: CostNamespaceLabels
    app_name: str
    cluster_name: str
    cluster_external_id: str | None


def get_cost_namespaces(
    gql_api: GqlApi,
) -> list[CostNamespace]:
    variables = {
        "filter": {
            "cluster": {
                "filter": {
                    "enableCostReport": True,
                },
            },
        },
    }
    namespaces = query(gql_api.query, variables=variables).namespaces or []
    return [
        CostNamespace(
            name=namespace.name,
            labels=CostNamespaceLabels.parse_obj(namespace.labels or {}),
            app_name=namespace.app.name,
            cluster_name=namespace.cluster.name,
            cluster_external_id=namespace.cluster.spec.external_id
            if namespace.cluster.spec
            else None,
        )
        for namespace in namespaces
    ]
