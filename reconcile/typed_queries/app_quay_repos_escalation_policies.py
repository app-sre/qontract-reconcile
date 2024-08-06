from reconcile.gql_definitions.common.app_quay_repos_escalation_policies import (
    AppV1,
    query,
)
from reconcile.utils import gql
from reconcile.utils.gql import GqlApi


def get_apps_quay_repos_escalation_policies(
    gql_api: GqlApi | None = None,
) -> list[AppV1]:
    api = gql_api if gql_api else gql.get_api()
    data = query(query_func=api.query)
    return list(data.apps or [])
